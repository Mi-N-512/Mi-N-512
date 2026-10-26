"""Collect GitHub data without logging repository identifiers or source contents."""
import collections
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from render import render

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_SOURCE = 500 * 1024 * 1024


def request(path, token, binary=False):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'profile-readme', 'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request('https://api.github.com' + path, headers=headers)
    with urllib.request.urlopen(req, timeout=90) as response:
        raw = response.read(MAX_ARCHIVE + 1)
    if len(raw) > MAX_ARCHIVE:
        raise ValueError('Response too large')
    return raw if binary else json.loads(raw)


def pages(path, token):
    result = []
    for page in range(1, 1001):
        separator = '&' if '?' in path else '?'
        rows = request(f'{path}{separator}per_page=100&page={page}', token)
        if not isinstance(rows, list):
            raise ValueError('Expected paginated list')
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise ValueError('Pagination limit reached')


def eligible(repos, config):
    owner = config['username'].lower()
    excluded = {name.lower() for name in config['exclude_repositories']}
    return [r for r in repos if r['owner']['login'].lower() == owner and not r['fork']
            and not r['archived'] and r['name'].lower() != owner
            and r['name'].lower() not in excluded and r.get('pushed_at')]


def extract_sources(raw, destination, excluded):
    """Read ordinary ZIP files only, rejecting traversal, symlinks and oversized archives."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_SOURCE:
            raise ValueError('Source size limit exceeded')
        for info in archive.infolist():
            parts = PurePosixPath(info.filename).parts
            if info.is_dir() or len(parts) < 2:
                continue
            if '..' in parts or '\\' in info.filename or any(':' in part for part in parts):
                raise ValueError('Unsafe source path')
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                continue
            if info.filename.startswith('/'):
                raise ValueError('Unsafe source entry')
            if any(part in excluded for part in parts[1:-1]):
                continue
            name = parts[-1]
            if name.endswith(('.min.js', '.min.css', '.map', '.lock', '.zip', '.tar', '.gz', '.jar', '.png', '.jpg')):
                continue
            if info.file_size > 5 * 1024 * 1024:
                continue
            target = destination.joinpath(*parts[1:])
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Unsafe source destination')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def count_lines(raw, config):
    with tempfile.TemporaryDirectory(prefix='profile-source-') as folder:
        source = Path(folder) / 'source'
        source.mkdir()
        extract_sources(raw, source, set(config['exclude_directories']))
        report = Path(folder) / 'counts.json'
        command = [os.environ.get('CLOC', 'cloc')]
        if os.environ.get('CLOC_PERL'):
            command.insert(0, os.environ['CLOC_PERL'])
        subprocess.run(command + [source.as_posix(), '--json', '--quiet', '--skip-archive=\\.(zip|tar|gz|bz2|xz|7z|jar|war)$',
                                  '--exclude-lang=' + ','.join(config['exclude_languages']),
                                  '--out=' + report.as_posix()], check=True, capture_output=True, timeout=180)
        if not report.exists():
            return {}
        counts = json.loads(report.read_text(encoding='utf-8'))
        return {k: v['code'] for k, v in counts.items() if k not in ('header', 'SUM') and v['code'] > 0}


def collect(config):
    private_token = os.environ.get('PROFILE_READ_TOKEN', '')
    token = private_token or os.environ.get('GH_TOKEN', '')
    username = urllib.parse.quote(config['username'], safe='')
    endpoint = '/user/repos?affiliation=owner&visibility=all' if private_token else f'/users/{username}/repos?type=owner'
    repositories = eligible(pages(endpoint, token), config)
    totals = collections.Counter()
    today = dt.datetime.now(dt.timezone.utc).date()
    dates = [(today-dt.timedelta(days=i)).isoformat() for i in reversed(range(28))]
    activity = {kind: collections.Counter() for kind in ('commits', 'issues', 'pulls')}
    dates_set = set(dates)
    def inspect(repo):
        lines = {}
        commits, issues, pulls = collections.Counter(), collections.Counter(), collections.Counter()
        skipped = 0
        # Identifiers remain in memory only. No source code from a repository is executed.
        path = '/repos/' + '/'.join(urllib.parse.quote(s, safe='') for s in (config['username'], repo['name']))
        if repo.get('size', 0) and (not repo['private'] or config['include_private_languages']):
            try:
                raw = request(path + '/zipball/' + urllib.parse.quote(repo['default_branch'], safe=''), token, binary=True)
                lines = count_lines(raw, config)
            except ValueError as error:
                if str(error) not in {'Response too large', 'Source size limit exceeded'}:
                    raise
                skipped = 1
        # Private repositories add to the daily totals only; nothing else about them is kept.
        if repo.get('size', 0) and (not repo['private'] or private_token):
            # Every branch, deduplicated by commit so merged work is counted once.
            query = urllib.parse.urlencode({'author': config['username'], 'since': dates[0]+'T00:00:00Z', 'until': today.isoformat()+'T23:59:59Z'})
            seen = {}
            for branch in pages(path + '/branches', token):
                ref = urllib.parse.urlencode({'sha': branch['name']})
                for commit in pages(path + f'/commits?{query}&{ref}', token):
                    seen[commit['sha']] = commit['commit']['committer']['date'][:10]
            for day in seen.values():
                if day in dates_set:
                    commits[day] += 1
        if not repo['private'] or private_token:
            # Issues and pull requests opened by this account. The issues endpoint returns both.
            query = urllib.parse.urlencode({'creator': config['username'], 'state': 'all', 'since': dates[0]+'T00:00:00Z'})
            try:
                for item in pages(path + '/issues?' + query, token):
                    day = item['created_at'][:10]
                    if day in dates_set:
                        (pulls if 'pull_request' in item else issues)[day] += 1
            except urllib.error.HTTPError as error:
                # 410: issues turned off. 403/404: the read token lacks issue or pull request access.
                if error.code not in (403, 404, 410):
                    raise
        return lines, (commits, issues, pulls), skipped
    skipped_total = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for index, (lines, counts, skipped) in enumerate(pool.map(inspect, repositories), 1):
            totals.update(lines)
            for kind, counter in zip(('commits', 'issues', 'pulls'), counts):
                activity[kind].update(counter)
            skipped_total += skipped
            if index % 25 == 0:
                print(f'Processed {index} repositories.', flush=True)
    private_scope = bool(private_token and config['include_private_languages'])
    coverage = 'Includes accessible private repositories in aggregate.' if private_scope else 'Public repositories only.'
    if skipped_total:
        coverage += f' {skipped_total} oversized repositories excluded from line counts (100 MiB archive / 500 MiB expanded limit).'
    return {'languages': dict(totals), 'repositories': repositories,
            'activity': [{'date': day, 'commits': activity['commits'][day], 'issues': activity['issues'][day],
                          'pulls': activity['pulls'][day],
                          'count': sum(activity[kind][day] for kind in activity)} for day in dates],
            'activity_private': bool(private_token),
            'updated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            'coverage': coverage}


def main():
    config = json.loads((ROOT/'profile.json').read_text(encoding='utf-8'))
    # Collect completely before writing. Any collection failure keeps the previous profile intact.
    data = collect(config)
    with tempfile.TemporaryDirectory(prefix='profile-render-') as folder:
        render(config, data, folder)
        shutil.copytree(Path(folder)/'assets', ROOT/'assets', dirs_exist_ok=True)
        for sub in ('', 'dark'):
            for i in range(1, 4):
                if not (Path(folder)/'assets'/sub/f'project-{i}.svg').exists():
                    (ROOT/'assets'/sub/f'project-{i}.svg').unlink(missing_ok=True)
        shutil.copyfile(Path(folder)/'README.md', ROOT/'README.md')
    print('Profile refreshed successfully.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Avoid URLs, credentials, private repository names and source paths in public Actions logs.
        code = f'HTTP {error.code}' if isinstance(error, urllib.error.HTTPError) else type(error).__name__
        safe_errors = {'Response too large', 'Source size limit exceeded', 'Unsafe source path', 'Unsafe source entry', 'Unsafe source destination', 'Pagination limit reached', 'Expected paginated list'}
        if str(error) in safe_errors:
            code += ': ' + str(error)
        print(f'::error::Profile refresh failed ({code}); existing published assets were retained. Check token access, API limits and cloc availability.', file=sys.stderr)
        sys.exit(1)
