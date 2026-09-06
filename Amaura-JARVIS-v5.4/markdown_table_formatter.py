import re

def format_markdown_table(text: str) -> str:
    lines = text.splitlines()
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if '|' in line and (i + 1 < len(lines) and '|' in lines[i+1] and '---' in lines[i+1]):
            table_lines = []
            while i < len(lines) and '|' in lines[i]:
                table_lines.append(lines[i])
                i += 1
            
            def parse_row(r):
                parts = r.split('|')
                # Remove empty strings at start/end if they are just boundaries
                if parts and not parts[0].strip(): parts = parts[1:]
                if parts and not parts[-1].strip(): parts = parts[:-1]
                return [p.strip() for p in parts]

            parsed_rows = [parse_row(r) for r in table_lines]
            
            num_cols = max(len(r) for r in parsed_rows)
            col_widths = [0] * num_cols
            for row in parsed_rows:
                for idx, cell in enumerate(row):
                    col_widths[idx] = max(col_widths[idx], len(cell))
            
            # Ensure min width 3 for delimiter row
            col_widths = [max(w, 3) for w in col_widths]
            
            formatted_table = []
            for idx, row in enumerate(parsed_rows):
                new_row = []
                for c_idx in range(num_cols):
                    cell = row[c_idx] if c_idx < len(row) else ""
                    if idx == 1: # Delimiter row
                        align = cell
                        left = align.startswith(':')
                        right = align.endswith(':')
                        width = col_widths[c_idx]
                        if left and right:
                            content = ":" + "-" * (width - 2) + ":"
                        elif left:
                            content = ":" + "-" * (width - 1)
                        elif right:
                            content = "-" * (width - 1) + ":"
                        else:
                            content = "-" * width
                        new_row.append(content)
                    else:
                        new_row.append(cell.ljust(col_widths[c_idx]))
                formatted_table.append("|" + "|".join(new_row) + "|")
            result.extend(formatted_table)
        else:
            result.append(line)
            i += 1
    return "\n".join(result)
