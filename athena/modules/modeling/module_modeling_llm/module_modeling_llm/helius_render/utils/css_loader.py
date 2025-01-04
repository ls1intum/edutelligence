import os

def load_css() -> str:
    """
    Load the CSS styles from the styles.css file
    """
    base_dir = os.path.dirname(os.path.dirname(__file__))
    styles_path = os.path.join(base_dir, 'styles', 'styles.css')

    try:
        with open(styles_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: styles.css not found at {styles_path}. Styles will not be applied.")
        return ""