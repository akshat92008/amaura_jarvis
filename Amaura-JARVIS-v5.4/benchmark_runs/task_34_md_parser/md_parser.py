def parse_markdown(md_text: str) -> str:
    """Parse markdown text and convert it to HTML.

    Args:
        md_text: The markdown text to parse.

    Returns:
        str: The parsed HTML.
    """
    lines = md_text.split('\n')
    html_lines = []
    
    for line in lines:
        stripped_line = line.strip()
        
        # Handle headers
        if stripped_line.startswith('# '):
            html_lines.append(f"<h1>{stripped_line[2:]}</h1>")
        elif stripped_line.startswith('## '):
            html_lines.append(f"<h2>{stripped_line[3:]}</h2>")
        elif stripped_line.startswith('### '):
            html_lines.append(f"<h3>{stripped_line[4:]}</h3>")
        
        # Handle bold and italic
        elif '**' in stripped_line and '*' in stripped_line:
            parts = stripped_line.split('**')
            bold_parts = [f"<b>{part}</b>" if i % 2 == 1 else part for i, part in enumerate(parts)]
            bold_text = ''.join(bold_parts)
            parts = bold_text.split('*')
            italic_parts = [f"<i>{part}</i>" if i % 2 == 1 else part for i, part in enumerate(parts)]
            html_lines.append(f"<p>{''.join(italic_parts)}</p>")
        
        # Handle bold
        elif '**' in stripped_line:
            parts = stripped_line.split('**')
            bold_parts = [f"<b>{part}</b>" if i % 2 == 1 else part for i, part in enumerate(parts)]
            html_lines.append(f"<p>{''.join(bold_parts)}</p>")
        
        # Handle italic
        elif '*' in stripped_line:
            parts = stripped_line.split('*')
            italic_parts = [f"<i>{part}</i>" if i % 2 == 1 else part for i, part in enumerate(parts)]
            html_lines.append(f"<p>{''.join(italic_parts)}</p>")
        
        # Handle paragraphs
        elif stripped_line:
            html_lines.append(f"<p>{stripped_line}</p>")
        
    return '\n'.join(html_lines)