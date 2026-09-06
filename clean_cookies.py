import os

def clean_cookies(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    clean_lines = []
    clean_lines.append("# Netscape HTTP Cookie File\n")
    clean_lines.append("# https://curl.haxx.se/rfc/cookie_spec.html\n")
    clean_lines.append("# This is a generated file! Do not edit.\n\n")

    for line in lines:
        if line.startswith('#') or not line.strip():
            continue
        parts = line.strip().split('\t')
        if len(parts) >= 7:
            domain = parts[0]
            if "youtube.com" in domain or "google.com" in domain:
                clean_lines.append(line)

    with open(output_file, 'w', encoding='utf-8', newline='\n') as f:
        f.writelines(clean_lines)

if __name__ == "__main__":
    clean_cookies("cookies.txt", "cookies.txt")
