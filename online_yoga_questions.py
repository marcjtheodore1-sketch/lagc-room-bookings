"""Editable online yoga registration questions and submitted-answer validation."""

QUESTION_TYPES = {
    'choice': 'Multiple choice (one answer)',
    'short': 'Short answer',
    'long': 'Long answer',
    'checkbox': 'Checkbox',
}
MAX_QUESTIONS = 16
ANSWER_LIMITS = {'short': 240, 'long': 1200}


def question(key, label, kind='long', help_text='', choices=(), required=False, enabled=True):
    return {
        'key': key, 'label': label, 'kind': kind, 'help_text': help_text,
        'choices': list(choices), 'required': required, 'enabled': enabled,
    }


DEFAULT_QUESTIONS = [
    question('experience', 'Have you done yoga before?', kind='choice', choices=('Yes', 'No', 'A little')),
    question('adapt', 'Please tell us anything Marlijn should know so the online session can be adapted safely for you.',
             help_text='For example, you can ask for seated options or tell Marlijn what would make movement more comfortable. Share only what she needs to support you in this session.'),
    question('avoid', 'Is there anything you would like Marlijn to avoid?',
             help_text='For example, certain movements, positions or breathing exercises.'),
    question('access', 'Is there anything about the way you experience, process, communicate, move or learn that would help Marlijn support you online?',
             help_text='For example, communication or sensory preferences, or a way of explaining movements that works for you.'),
    question('agree', 'I understand that I can choose how much to take part and stop or rest whenever I need to. I’ll respect other participants’ privacy and keep the session free of recordings and screenshots.',
             kind='checkbox', required=True),
]


def parse_editor_question(form, key):
    label = form.get('label', '').strip()
    help_text = form.get('help_text', '').strip()
    kind = form.get('kind', '')
    if not 1 <= len(label) <= 500 or len(help_text) > 600 or kind not in QUESTION_TYPES:
        raise ValueError('Enter a question, choose an answer type and check the text limits shown.')
    choices = [line.strip() for line in form.get('choices', '').splitlines() if line.strip()] if kind == 'choice' else []
    if kind == 'choice' and (not 2 <= len(choices) <= 12 or len(set(choices)) != len(choices) or any(len(c) > 120 for c in choices)):
        raise ValueError('Enter 2 to 12 different answer options on separate lines, up to 120 characters each.')
    return question(key, label, kind, help_text, choices,
                    form.get('required') == 'yes', form.get('enabled') == 'yes')


def parse_answers(questions, form):
    answers = []
    for field in questions:
        if not field['enabled']:
            continue
        field_name = 'answer_' + field['key']
        value = form.get(field_name, '').strip()
        if len(form.getlist(field_name)) > 1:
            raise ValueError('Please give one answer to each question.')
        if not value:
            if field['required']:
                raise ValueError(f'Please answer this question: {field["label"]}')
            continue
        kind = field['kind']
        if kind == 'checkbox' and value != 'yes':
            raise ValueError('Please check the checkbox answers.')
        if kind == 'choice' and value not in field['choices']:
            raise ValueError('Please choose one of the available answers.')
        if kind in ANSWER_LIMITS and len(value) > ANSWER_LIMITS[kind]:
            raise ValueError('An answer is too long. Check the limits shown on the form.')
        answers.append({'question': field['label'], 'value': 'Yes' if kind == 'checkbox' else value})
    return answers
