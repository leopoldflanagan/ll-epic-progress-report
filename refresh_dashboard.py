#!/usr/bin/env python3
"""
LL Epic Progress Dashboard - Auto Refresh Script
Extracts fresh data from Jira and updates the HTML dashboard
"""

import os
import sys
import json
import requests
from datetime import datetime
from typing import Dict, List, Any
import re

# Jira Configuration
JIRA_BASE_URL = "https://wellfit.atlassian.net"
JIRA_API_BASE = f"{JIRA_BASE_URL}/rest/api/3"
CLOUD_ID = "120843f0-4f3e-4c73-adfb-9880d7acb06c"

# Epic Keys (27 active epics)
ACTIVE_EPICS = [
    "LL-618", "LL-601", "LL-361", "LL-359", "LL-355", "LL-354", "LL-350",
    "LL-349", "LL-328", "LL-311", "LL-310", "LL-309", "LL-308", "LL-307",
    "LL-300", "LL-200", "LL-142", "LL-140", "LL-131", "LL-120", "LL-115",
    "LL-106", "LL-85", "LL-78", "LL-75", "LL-74", "LL-48"
]

# Status mappings
DONE_STATUSES = ['Done', 'Closed']
IN_PROGRESS_STATUSES = ['In Development', 'In QA', 'PR Created', 'PR Merged', 'Ready for QA', 'WAITING REVIEW', 'In Stage', 'Ready Prod']
TODO_STATUSES = ['Backlog', 'Ready for Development', 'READY TO DEVELOP']

def get_jira_session():
    """Create authenticated Jira session"""
    email = os.environ.get('JIRA_EMAIL')
    api_token = os.environ.get('JIRA_API_TOKEN')
    
    if not email or not api_token:
        raise ValueError("JIRA_EMAIL and JIRA_API_TOKEN environment variables required")
    
    session = requests.Session()
    session.auth = (email, api_token)
    session.headers.update({'Accept': 'application/json'})
    return session

def fetch_epics(session: requests.Session) -> Dict[str, Any]:
    """Fetch all active epics"""
    jql = f"project = LL AND key in ({','.join(ACTIVE_EPICS)}) AND issuetype = Epic"
    
    params = {
        'jql': jql,
        'fields': 'key,summary,status',
        'maxResults': 100
    }
    
    response = session.get(f"{JIRA_API_BASE}/search", params=params)
    response.raise_for_status()
    
    epics = {}
    for issue in response.json()['issues']:
        epics[issue['key']] = {
            'key': issue['key'],
            'name': issue['fields']['summary'],
            'status': issue['fields']['status']['name']
        }
    
    return epics

def fetch_stories_for_epics(session: requests.Session, epic_keys: List[str]) -> List[Dict[str, Any]]:
    """Fetch all stories for given epics"""
    jql = f"""
    parent in ({','.join(epic_keys)}) 
    AND issuetype in (Story, Task, Bug, TechDebt, Spike)
    AND (labels is EMPTY OR labels not in (admin-tracking, Reenbit))
    ORDER BY parent ASC, status ASC
    """
    
    all_stories = []
    start_at = 0
    max_results = 100
    
    while True:
        params = {
            'jql': jql,
            'fields': 'key,summary,parent,status',
            'startAt': start_at,
            'maxResults': max_results
        }
        
        response = session.get(f"{JIRA_API_BASE}/search", params=params)
        response.raise_for_status()
        data = response.json()
        
        for issue in data['issues']:
            story = {
                'key': issue['key'],
                'summary': issue['fields']['summary'],
                'parent': issue['fields']['parent']['key'],
                'status': issue['fields']['status']['name']
            }
            all_stories.append(story)
        
        # Check pagination
        if start_at + max_results >= data['total']:
            break
        start_at += max_results
    
    return all_stories

def categorize_status(status_name: str) -> str:
    """Categorize status into done/inProgress/todo"""
    if status_name in DONE_STATUSES:
        return 'done'
    elif status_name in IN_PROGRESS_STATUSES:
        return 'inProgress'
    else:
        return 'todo'

def aggregate_epic_data(epics: Dict[str, Any], stories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate story counts per epic"""
    epic_stats = {key: {'total': 0, 'done': 0, 'inProgress': 0, 'todo': 0} for key in epics.keys()}
    
    for story in stories:
        parent_key = story['parent']
        if parent_key in epic_stats:
            epic_stats[parent_key]['total'] += 1
            category = categorize_status(story['status'])
            epic_stats[parent_key][category] += 1
    
    # Build epic list
    epic_list = []
    for key, epic_info in epics.items():
        stats = epic_stats[key]
        if stats['total'] > 0:  # Only include epics with stories
            percent = round((stats['done'] / stats['total']) * 100) if stats['total'] > 0 else 0
            epic_list.append({
                'key': key,
                'name': epic_info['name'],
                'epicStatus': epic_info['status'],
                'total': stats['total'],
                'done': stats['done'],
                'inProgress': stats['inProgress'],
                'todo': stats['todo'],
                'percentComplete': percent
            })
    
    # Sort by key
    epic_list.sort(key=lambda x: x['key'])
    return epic_list

def generate_week_data(epics_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate week data structure"""
    total_stories = sum(e['total'] for e in epics_data)
    total_done = sum(e['done'] for e in epics_data)
    total_in_progress = sum(e['inProgress'] for e in epics_data)
    total_todo = sum(e['todo'] for e in epics_data)
    
    overall_percent = round((total_done / total_stories) * 100) if total_stories > 0 else 0
    
    today = datetime.now()
    week_name = f"W{((today.day - 1) // 7) + 1}-Sprint{(today.month - 1) // 2 + 8}-26"
    date_str = today.strftime('%B %d, %Y')
    
    return {
        'date': date_str,
        'totalEpics': len([e for e in epics_data if e['total'] > 0]),
        'totalStories': total_stories,
        'excludedWNI': 23,
        'excludedReebit': 6,
        'summary': {
            'totalDone': total_done,
            'totalInProgress': total_in_progress,
            'totalTodo': total_todo,
            'overallPercent': overall_percent
        },
        'weeklyThroughput': {
            'completed': total_done,
            'delta': None,
            'vsWeek': None
        },
        'epics': epics_data
    }

def update_html_with_data(html_path: str, week_name: str, week_data: Dict[str, Any]):
    """Update HTML file with new data"""
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # Find the WEEKS object and update the current week
    pattern = rf"'{week_name}':\s*\{{[^}}]*?\}},?"
    
    # Generate new week data JS
    new_week_js = f"'{week_name}':{json.dumps(week_data, separators=(',', ':'))}"
    
    # Check if week exists
    if re.search(pattern, html_content, re.DOTALL):
        # Update existing week
        html_content = re.sub(pattern, new_week_js + ',', html_content, flags=re.DOTALL)
    else:
        # Add new week before closing };
        html_content = re.sub(
            r"(const WEEKS=\{[^}]+)(\}\s*;)",
            rf"\1,{new_week_js}\2",
            html_content,
            flags=re.DOTALL
        )
    
    # Update currentWeek variable
    html_content = re.sub(
        r"let currentWeek='[^']+';",
        f"let currentWeek='{week_name}';",
        html_content
    )
    
    # Update timestamp comment
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    if '<!-- Last auto-update:' in html_content:
        html_content = re.sub(
            r'<!-- Last auto-update: [^>]+ -->',
            f'<!-- Last auto-update: {timestamp} -->',
            html_content
        )
    else:
        html_content = html_content.replace(
            '<script>',
            f'<!-- Last auto-update: {timestamp} -->\n<script>',
            1
        )
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✅ Updated {html_path} with fresh data for {week_name}")

def main():
    """Main execution"""
    print("🔄 LL Epic Progress Dashboard - Auto Refresh")
    print("=" * 50)
    
    try:
        # Setup
        session = get_jira_session()
        html_path = 'index.html'
        
        if not os.path.exists(html_path):
            print(f"❌ Error: {html_path} not found")
            sys.exit(1)
        
        # Fetch data
        print("📡 Fetching epics from Jira...")
        epics = fetch_epics(session)
        print(f"   Found {len(epics)} active epics")
        
        print("📡 Fetching stories from Jira...")
        stories = fetch_stories_for_epics(session, list(epics.keys()))
        print(f"   Found {len(stories)} stories")
        
        # Process
        print("⚙️  Processing data...")
        epics_data = aggregate_epic_data(epics, stories)
        week_data = generate_week_data(epics_data)
        
        # Get current week name
        today = datetime.now()
        week_name = f"W{((today.day - 1) // 7) + 1}-Sprint{(today.month - 1) // 2 + 8}-26"
        
        print(f"📊 Summary for {week_name}:")
        print(f"   • Total Stories: {week_data['totalStories']}")
        print(f"   • Done: {week_data['summary']['totalDone']} ({week_data['summary']['overallPercent']}%)")
        print(f"   • In Progress: {week_data['summary']['totalInProgress']}")
        print(f"   • Todo: {week_data['summary']['totalTodo']}")
        print(f"   • Active Epics: {week_data['totalEpics']}")
        
        # Update HTML
        print("💾 Updating HTML dashboard...")
        update_html_with_data(html_path, week_name, week_data)
        
        print("\n✨ Refresh complete!")
        print(f"🔗 Dashboard: https://leopoldflanagan.github.io/ll-epic-progress-report/")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
