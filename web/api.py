from flask import Flask, request, jsonify
from flask_cors import CORS
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from oss_issue_scout.cli import _search_recommended
from oss_issue_scout.github_api import GitHubAPIError

app = Flask(__name__)
CORS(app, origins=['http://localhost:8000', 'http://127.0.0.1:8000', 'http://[::]:8000'], allow_headers=['Authorization', 'Content-Type'])

def validate_int(value, field_name):
    if value == '' or value is None:
        return None
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Invalid {field_name}: must be an integer")

@app.route('/api/search', methods=['GET'])
def search():
    try:
        language = request.args.get('language', '')
        label = request.args.get('label', '')
        stars_min = request.args.get('stars_min', '')
        limit = request.args.get('limit', '5')
        preset = request.args.get('preset', 'default')
        updated_days = request.args.get('updated_days', '')
        query = request.args.get('query', '')
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        args_obj = argparse.Namespace()
        args_obj.language = language if language else None
        args_obj.stars_min = validate_int(stars_min, 'stars_min')
        args_obj.label = label if label else None
        args_obj.updated_days = validate_int(updated_days, 'updated_days')
        args_obj.repo_updated_days = None
        args_obj.limit = validate_int(limit, 'limit')
        args_obj.preset = preset
        args_obj.format = 'json'
        args_obj.query = query if query else None
        
        if token:
            original_token = os.environ.get('GITHUB_TOKEN')
            try:
                os.environ['GITHUB_TOKEN'] = token
                results = _search_recommended(args_obj)
            finally:
                if original_token is None:
                    os.environ.pop('GITHUB_TOKEN', None)
                else:
                    os.environ['GITHUB_TOKEN'] = original_token
        else:
            results = _search_recommended(args_obj)
        
        issues = []
        for result in results:
            issue = result.issue
            issues.append({
                'repo': issue.repo,
                'title': issue.title,
                'url': issue.url,
                'labels': [label for label in issue.labels],
                'stars': issue.stars,
                'score': result.score,
                'reasons': result.reasons,
                'warnings': result.warnings
            })
        
        return jsonify({'issues': issues})
    
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except GitHubAPIError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    import os
    debug_enabled = os.environ.get('OSS_ISSUE_SCOUT_DEBUG', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
    app.run(host='127.0.0.1', port=5000, debug=debug_enabled)
