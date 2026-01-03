"""LLM prompt templates for outreach generation."""

EMAIL_OUTREACH_PROMPT = """Generate a personalized cold email for lead outreach.

Business Information:
- Name: {business_name}
- Category: {category}
- Rating: {rating}/5 ({review_count} reviews)
- Location: {address}
- Website: {website}
{owner_info}

Company Intelligence:
{company_intel}

Lead Insights:
- Pain Points: {pain_points}
- Personalization Hooks: {personalization_hooks}
- Recent News: {recent_news}

Requirements:
1. Keep it short (3-4 sentences max)
2. Mention something specific about their business using the insights above
3. Be professional but friendly
4. Include a clear call-to-action
5. Don't be pushy or salesy
6. If there's recent news, reference it naturally

Your product/service context: {product_context}

Generate ONLY the email body (no subject line, no signature).
"""

EMAIL_SUBJECT_PROMPT = """Generate a short, compelling email subject line for this business:

Business: {business_name}
Category: {category}
Context: {product_context}
Personalization Hook: {personalization_hook}

Requirements:
- Max 50 characters
- No clickbait
- Professional tone
- Use the personalization hook if relevant

Generate ONLY the subject line, nothing else.
"""

LINKEDIN_MESSAGE_PROMPT = """Generate a LinkedIn connection message for lead outreach.

Business Information:
- Name: {business_name}
- Owner/Contact: {owner_name}
- Category: {category}
- Rating: {rating}/5
- Location: {address}

Lead Insights:
- Pain Points: {pain_points}
- Personalization Hooks: {personalization_hooks}

Requirements:
1. Max 300 characters (LinkedIn limit)
2. Personal and professional
3. Reference something specific about their business using the insights
4. Soft call-to-action

Your product/service context: {product_context}

Generate ONLY the message, nothing else.
"""

WHATSAPP_MESSAGE_PROMPT = """Generate a WhatsApp business outreach message.

Business Information:
- Name: {business_name}
- Category: {category}
- Rating: {rating}/5
- Location: {address}

Lead Insights:
- Pain Points: {pain_points}
- Personalization Hooks: {personalization_hooks}

Requirements:
1. Keep it short and conversational
2. Friendly but professional
3. Include a question to encourage response
4. No long paragraphs
5. Reference a pain point or hook naturally

Your product/service context: {product_context}

Generate ONLY the message, nothing else.
"""

COLD_CALL_SCRIPT_PROMPT = """Generate a cold call script for sales outreach.

Business Information:
- Name: {business_name}
- Category: {category}
- Rating: {rating}/5 ({review_count} reviews)
- Location: {address}
- Owner/Contact: {owner_name}

Company Intelligence:
{company_intel}

Lead Insights:
- Pain Points: {pain_points}
- Recommended Approach: {recommended_approach}

Requirements:
1. Brief intro (who you are, why calling)
2. Hook based on their specific pain points
3. Value proposition in 1-2 sentences
4. Qualifying question
5. Close with next step

Your product/service context: {product_context}

Format as a script with [PAUSE] markers for natural conversation.
"""

DEFAULT_PRODUCT_CONTEXT = """We help local businesses improve their online presence and attract more customers through digital marketing solutions."""
