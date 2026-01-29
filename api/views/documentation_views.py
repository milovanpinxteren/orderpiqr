import os
import re
from django.http import HttpResponse
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema


def markdown_to_html(markdown_text):
    """
    Simple markdown to HTML converter for basic formatting.
    Handles: headers, code blocks, inline code, bold, tables, lists, links, horizontal rules.
    """
    html = markdown_text

    # Escape HTML characters first (but preserve our markdown)
    html = html.replace('&', '&amp;')
    html = html.replace('<', '&lt;')
    html = html.replace('>', '&gt;')

    # Code blocks (``` ... ```) - must be done before other processing
    def replace_code_block(match):
        lang = match.group(1) or ''
        code = match.group(2)
        # Unescape for code blocks
        code = code.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        return f'<pre><code class="language-{lang}">{code}</code></pre>'

    html = re.sub(r'```(\w*)\n(.*?)```', replace_code_block, html, flags=re.DOTALL)

    # Inline code (`code`)
    html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)

    # Headers
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)

    # Bold
    html = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', html)

    # Links [text](url)
    html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', html)

    # Horizontal rules
    html = re.sub(r'^---+$', r'<hr>', html, flags=re.MULTILINE)

    # Tables
    lines = html.split('\n')
    in_table = False
    new_lines = []
    for i, line in enumerate(lines):
        # Check if this is a table row
        if '|' in line and line.strip().startswith('|'):
            cells = [c.strip() for c in line.strip().strip('|').split('|')]

            # Check if next line is separator (|---|---|)
            is_header = (i + 1 < len(lines) and
                         re.match(r'^\|[\s\-:|]+\|$', lines[i + 1].strip()))

            # Check if this is the separator line itself
            if re.match(r'^[\s\-:|]+$', line.strip().strip('|').replace('|', '')):
                continue  # Skip separator lines

            if not in_table:
                new_lines.append('<table class="api-table">')
                in_table = True

            if is_header:
                new_lines.append('<thead><tr>')
                for cell in cells:
                    new_lines.append(f'<th>{cell}</th>')
                new_lines.append('</tr></thead><tbody>')
            else:
                new_lines.append('<tr>')
                for cell in cells:
                    new_lines.append(f'<td>{cell}</td>')
                new_lines.append('</tr>')
        else:
            if in_table:
                new_lines.append('</tbody></table>')
                in_table = False
            new_lines.append(line)

    if in_table:
        new_lines.append('</tbody></table>')

    html = '\n'.join(new_lines)

    # Unordered lists
    html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    # Wrap consecutive li elements in ul
    html = re.sub(r'((?:<li>.*?</li>\n?)+)', r'<ul>\1</ul>', html)

    # Paragraphs - wrap lines that aren't already in tags
    lines = html.split('\n')
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('<') and not stripped.endswith('>'):
            new_lines.append(f'<p>{line}</p>')
        else:
            new_lines.append(line)
    html = '\n'.join(new_lines)

    return html


def get_documentation_html(language='en'):
    """Read and convert the markdown documentation to HTML."""
    filename = 'API_DOCUMENTATION_EN.md' if language == 'en' else 'API_DOCUMENTATION_NL.md'
    filepath = os.path.join(settings.BASE_DIR, 'docs', filename)

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        return markdown_to_html(markdown_content)
    except FileNotFoundError:
        return f'<p>Documentation file not found: {filename}</p>'


HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OrderPiqR API Documentation</title>
    <style>
        :root {{
            --primary-color: #2c3e50;
            --secondary-color: #3498db;
            --bg-color: #f8f9fa;
            --code-bg: #2d2d2d;
            --border-color: #e1e4e8;
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: var(--bg-color);
        }}

        .nav-bar {{
            background: var(--primary-color);
            padding: 15px 20px;
            margin: -20px -20px 30px -20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }}

        .nav-bar a {{
            color: white;
            text-decoration: none;
            padding: 8px 16px;
            border-radius: 4px;
            transition: background 0.2s;
        }}

        .nav-bar a:hover {{
            background: rgba(255,255,255,0.1);
        }}

        .nav-bar .brand {{
            font-weight: bold;
            font-size: 1.2em;
        }}

        .nav-links {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }}

        .lang-switch {{
            background: var(--secondary-color);
            border-radius: 4px;
        }}

        h1 {{
            color: var(--primary-color);
            border-bottom: 3px solid var(--secondary-color);
            padding-bottom: 10px;
            margin-top: 40px;
        }}

        h1:first-of-type {{
            margin-top: 0;
        }}

        h2 {{
            color: var(--primary-color);
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 8px;
            margin-top: 30px;
        }}

        h3 {{
            color: #555;
            margin-top: 25px;
        }}

        pre {{
            background: var(--code-bg);
            color: #f8f8f2;
            padding: 15px;
            border-radius: 6px;
            overflow-x: auto;
            font-size: 14px;
        }}

        code {{
            background: #e9ecef;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.9em;
        }}

        pre code {{
            background: none;
            padding: 0;
            color: inherit;
        }}

        .api-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            background: white;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            border-radius: 6px;
            overflow: hidden;
        }}

        .api-table th,
        .api-table td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }}

        .api-table th {{
            background: var(--primary-color);
            color: white;
            font-weight: 600;
        }}

        .api-table tr:hover {{
            background: #f5f5f5;
        }}

        .api-table tr:last-child td {{
            border-bottom: none;
        }}

        ul {{
            padding-left: 25px;
        }}

        li {{
            margin: 8px 0;
        }}

        a {{
            color: var(--secondary-color);
        }}

        hr {{
            border: none;
            border-top: 2px solid var(--border-color);
            margin: 40px 0;
        }}

        p {{
            margin: 10px 0;
        }}

        strong {{
            color: var(--primary-color);
        }}

        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}

            .nav-bar {{
                margin: -10px -10px 20px -10px;
                padding: 10px;
            }}

            pre {{
                font-size: 12px;
                padding: 10px;
            }}

            .api-table {{
                font-size: 14px;
            }}

            .api-table th,
            .api-table td {{
                padding: 8px 10px;
            }}
        }}
    </style>
</head>
<body>
    <nav class="nav-bar">
        <span class="brand">OrderPiqR API</span>
        <div class="nav-links">
            <a href="/api/docs/">Swagger UI</a>
            <a href="/api/redoc/">ReDoc</a>
            <a href="/api/">API Root</a>
            <a href="/api/documentation/{other_lang}/" class="lang-switch">{lang_label}</a>
        </div>
    </nav>
    <main>
        {content}
    </main>
</body>
</html>
'''


@extend_schema(exclude=True)
@api_view(['GET'])
@permission_classes([AllowAny])
def documentation_view(request, language='en'):
    """Render the API documentation as HTML."""
    if language not in ['en', 'nl']:
        language = 'en'

    content = get_documentation_html(language)

    other_lang = 'nl' if language == 'en' else 'en'
    lang_label = 'Nederlands' if language == 'en' else 'English'

    html = HTML_TEMPLATE.format(
        lang=language,
        content=content,
        other_lang=other_lang,
        lang_label=lang_label
    )

    return HttpResponse(html, content_type='text/html')
