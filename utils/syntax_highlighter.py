import sys
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QColor, QTextCharFormat, QFont, QSyntaxHighlighter, QTextDocument

# Helper function to create format
def format_text(color_name, style=''):
    """Return a QTextCharFormat with the given attributes."""
    _color = QColor()
    _color.setNamedColor(color_name)

    _format = QTextCharFormat()
    _format.setForeground(_color)
    if 'bold' in style:
        _format.setFontWeight(QFont.Weight.Bold)
    if 'italic' in style:
        _format.setFontItalic(True)

    return _format

# Define styles using the helper function - UPDATED FOR DARK THEME
# Colors inspired by typical dark IDE themes (like VS Code Dark+)
STYLES = {
    'keyword': format_text('#569cd6'),     # Blue for keywords (like import, for, if)
    'operator': format_text('#d4d4d4'),    # Default text color (light gray) for operators
    'brace': format_text('#d4d4d4'),       # Default text color for braces
    'defclass': format_text('#4ec9b0'),    # Teal for def/class names
    'string': format_text('#ce9178'),     # Orange-ish for strings
    'string2': format_text('#ce9178'),    # Orange-ish for triple-quoted strings
    'comment': format_text('#6a9955', 'italic'), # Green italic for comments
    'self': format_text('#9cdcfe'),        # Light blue for self
    'numbers': format_text('#b5cea8'),    # Olive-green for numbers
    'decorator': format_text('#d7ba7d'),   # Yellow-gold for decorators (@)
    'function_call': format_text('#dcdcaa'), # Light yellow for function calls
}


class PythonSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for the Python language."""

    # Python keywords
    keywords = [
        'and', 'assert', 'break', 'class', 'continue', 'def',
        'del', 'elif', 'else', 'except', 'exec', 'finally',
        'for', 'from', 'global', 'if', 'import', 'in',
        'is', 'lambda', 'not', 'or', 'pass', 'print', # Note: 'print' is keyword in Py2, function in Py3
        'raise', 'return', 'try', 'while', 'yield',
        'None', 'True', 'False', 'nonlocal', 'with', 'async', 'await'
    ]

    # Python operators - Use raw strings r'...' for regex patterns
    operators = [
        '=',
        # Comparison
        '==', '!=', '<', '<=', '>', '>=',
        # Arithmetic
        r'\+', '-', r'\*', r'/', r'//', r'\%', r'\*\*',
        # In-place
        r'\+=', '-=', r'\*=', r'/=', r'\%=',
        # Bitwise
        r'\^', r'\|', r'\&', r'\~', '>>', '<<',
    ]

    # Python braces - Use raw strings r'...' for regex patterns
    braces = [
        r'\{', r'\}', r'\(', r'\)', r'\[', r'\]',
    ]

    def __init__(self, parent_widget): # Expecting the parent widget (e.g., QTextEdit)
        """
        Initializes the highlighter.
        Args:
            parent_widget: The parent QTextEdit widget or similar object providing a document().
        """
        if isinstance(parent_widget, QTextDocument):
             # If a document was passed directly, use it (maintain compatibility if needed)
             doc = parent_widget
             super().__init__(doc)
        elif hasattr(parent_widget, 'document') and callable(parent_widget.document):
             # If it's a widget-like object, get its document
             doc = parent_widget.document()
             super().__init__(doc)
        else:
             # Fallback or raise error if neither document nor widget with document method is provided
             raise TypeError("Parent must be a QTextDocument or an object with a document() method.")


        # Multi-line strings (expression, flag, style)
        # Ensure styles used here are defined in STYLES dictionary
        self.tri_single = (QRegularExpression("'''"), 1, STYLES['string2'])
        self.tri_double = (QRegularExpression('"""'), 2, STYLES['string2'])

        rules = []

        # Keyword, operator, and brace rules
        # Use raw strings r'...' for patterns containing \b or other sequences if needed
        rules += [(r'\b%s\b' % w, 0, STYLES['keyword']) for w in PythonSyntaxHighlighter.keywords]
        rules += [(r'%s' % o, 0, STYLES['operator']) for o in PythonSyntaxHighlighter.operators]
        rules += [(r'%s' % b, 0, STYLES['brace']) for b in PythonSyntaxHighlighter.braces]

        # All other rules
        rules += [
            # 'self' - Use raw string r'...' for \b
            (r'\bself\b', 0, STYLES['self']),

            # Decorators
            (r'@[a-zA-Z_][a-zA-Z0-9_]*', 0, STYLES['decorator']),

            # Function calls - Use raw string r'...' for \b
            # Updated regex to be less greedy and avoid highlighting class names before instantiation
            (r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?=\()', 1, STYLES['function_call']),

            # 'def' and 'class' followed by name - Use raw string r'...' for \b and \s
            (r'\b(def|class)\b\s+([A-Za-z_][A-Za-z0-9_]*)', 2, STYLES['defclass']), # Match name after def/class

            # Numeric literals - Use raw string r'...' for \b
            (r'\b[+-]?[0-9]+[lL]?\b', 0, STYLES['numbers']),
            (r'\b[+-]?0[xX][0-9A-Fa-f]+[lL]?\b', 0, STYLES['numbers']),
            (r'\b[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\b', 0, STYLES['numbers']),

            # Double-quoted string, possibly containing escape sequences - Use raw string r'...'
            (r'"[^"\\]*(\\.[^"\\]*)*"', 0, STYLES['string']),
            # Single-quoted string, possibly containing escape sequences - Use raw string r'...'
            (r"'[^'\\]*(\\.[^'\\]*)*'", 0, STYLES['string']),

            # From '#' until a newline
            (r'#[^\n]*', 0, STYLES['comment']),
        ]

        # Build a QRegularExpression for each pattern
        self.rules = [(QRegularExpression(pat), index, fmt) for (pat, index, fmt) in rules]


    def highlightBlock(self, text):
        """Apply syntax highlighting to the given block of text."""
        # Do other syntax formatting first
        for expression, nth, format_style in self.rules:
            match_iterator = expression.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                # Check if the captured group index 'nth' is valid for this match
                # The capturedTexts() list includes the full match at index 0.
                # A specific group index 'nth' refers to capture group 'nth'.
                capture_index = nth # nth=0 means full match, nth=1 means group 1, etc.
                if capture_index < len(match.capturedTexts()):
                    start_index = match.capturedStart(capture_index)
                    length = match.capturedLength(capture_index)
                    if start_index >= 0 and length > 0: # Ensure valid capture range
                         self.setFormat(start_index, length, format_style)

        self.setCurrentBlockState(0)

        # Do multi-line strings LAST to override other rules if needed
        in_multiline = self.match_multiline(text, *self.tri_single)
        if not in_multiline:
            in_multiline = self.match_multiline(text, *self.tri_double)


    def match_multiline(self, text, delimiter, in_state, style):
        """Do highlighting of multi-line strings. ``delimiter`` should be a
        ``QRegularExpression`` for triple-single-quotes or triple-double-quotes, and
        ``in_state`` should be a unique integer state value corresponding to the
        ``delimiter``.
        """
        start_index = 0
        add = 0 # Correction factor if previous state is multi-line

        # If inside a multi-line string from previous block, highlight from start
        if self.previousBlockState() == in_state:
            start_index = 0
            add = 0
            self.setCurrentBlockState(in_state) # Assume it continues unless delimiter is found
        else:
            # Look for the start of a multi-line string in the current block
            start_match = delimiter.match(text)
            if not start_match.hasMatch():
                 return False # No start found
            start_index = start_match.capturedStart()
            add = start_match.capturedLength()


        # Now look for the end delimiter from the potential start position
        end_match = delimiter.match(text, start_index + add)
        if end_match.hasMatch():
            # End delimiter found in this block
            end_index = end_match.capturedStart()
            length = (end_index - start_index) + end_match.capturedLength()
            self.setCurrentBlockState(0) # Multi-line ends here
        else:
            # End delimiter not found, highlight to end of block
            self.setCurrentBlockState(in_state)
            length = len(text) - start_index

        self.setFormat(start_index, length, style)
        return True # Multi-line string handled