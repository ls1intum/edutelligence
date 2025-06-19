import re
import pandas as pd
from bs4 import BeautifulSoup
import markdown

def clean_problem_statements(text):
    # Remove code blocks
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    # Remove inline code (`code`)
    text = re.sub(r'`[^`]*`', '', text)
    # Remove testid references
    text = re.sub(r'<testid>\d+</testid>', '', text)
    # Remove HTML tags and convert markdown to plain text
    soup = BeautifulSoup(markdown.markdown(text), 'html.parser')
    text = soup.get_text()
    # Remove special markdown characters and formatting
    text = re.sub(r'\[task\]|\[/task\]', '', text)  # Remove task tags
    text = re.sub(r'$begin:math:display$task$end:math:display$|$begin:math:display$/task$end:math:display$', '', text)
    text = re.sub(r'$begin:math:display$.*?$end:math:display$', '', text)
    text = re.sub(r'\$\$(.*?)\$\$', '', text)
    # Remove HTML styling and special characters
    text = re.sub(r'<tt.*?>(.*?)</tt>', '', text)
    text = re.sub(r'⎵', ' ', text)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'^\s+|\s+$', '', text, flags=re.MULTILINE)
    # Final cleanup
    text = text.strip()
    return text
