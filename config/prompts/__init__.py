"""LLM prompt templates with multi-language support."""

from config.prompts import en, id as id_prompts

SUPPORTED_LANGUAGES = {'en', 'id'}

def get_prompts(language: str = 'en'):
    """Get prompts for specified language.

    Args:
        language: Language code ('en', 'id')

    Returns:
        Module with prompt templates

    Example:
        >>> prompts = get_prompts('id')
        >>> prompts.EMAIL_OUTREACH_PROMPT
        'Buatkan email cold outreach...'
    """
    if language not in SUPPORTED_LANGUAGES:
        language = 'en'  # Fallback to English

    if language == 'id':
        return id_prompts
    return en


# Backward compatibility: expose English prompts at module level
EMAIL_OUTREACH_PROMPT = en.EMAIL_OUTREACH_PROMPT
EMAIL_SUBJECT_PROMPT = en.EMAIL_SUBJECT_PROMPT
LINKEDIN_MESSAGE_PROMPT = en.LINKEDIN_MESSAGE_PROMPT
WHATSAPP_MESSAGE_PROMPT = en.WHATSAPP_MESSAGE_PROMPT
COLD_CALL_SCRIPT_PROMPT = en.COLD_CALL_SCRIPT_PROMPT
DEFAULT_PRODUCT_CONTEXT = en.DEFAULT_PRODUCT_CONTEXT
LEAD_RESEARCH_PROMPT = en.LEAD_RESEARCH_PROMPT

__all__ = [
    'get_prompts',
    'SUPPORTED_LANGUAGES',
    'EMAIL_OUTREACH_PROMPT',
    'EMAIL_SUBJECT_PROMPT',
    'LINKEDIN_MESSAGE_PROMPT',
    'WHATSAPP_MESSAGE_PROMPT',
    'COLD_CALL_SCRIPT_PROMPT',
    'DEFAULT_PRODUCT_CONTEXT',
    'LEAD_RESEARCH_PROMPT',
    'en',
    'id_prompts',
]
