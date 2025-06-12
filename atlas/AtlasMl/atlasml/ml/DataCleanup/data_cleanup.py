import re
import pandas as pd
from bs4 import BeautifulSoup
import markdown

def clean_problem_statements(text):
    # 1. Remove HTML tags and convert markdown to plain text
    soup = BeautifulSoup(markdown.markdown(text), 'html.parser')
    text = soup.get_text()

    # 2. Remove special markdown characters and formatting
    text = re.sub(r'\[task\]|\[/task\]', '', text)  # Remove task tags
    text = re.sub(r'\[.*?\]', '', text)  # Remove markdown links
    text = re.sub(r'\$\$(.*?)\$\$', r'\1', text)  # Convert math expressions
    text = re.sub(r'`(.*?)`', r'\1', text)  # Remove code formatting

    # 3. Remove HTML styling and special characters
    text = re.sub(r'<tt.*?>(.*?)</tt>', r'\1', text)
    text = re.sub(r'⎵', ' ', text)  # Replace special space character

    # 4. Clean up whitespace
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
    text = re.sub(r'^\s+|\s+$', '', text, flags=re.MULTILINE)  # Trim lines

    # 5. Remove code blocks
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)

    # 7. Final cleanup
    text = text.strip()

    return text
