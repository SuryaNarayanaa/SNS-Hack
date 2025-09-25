from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from typing import Dict, Any
import re
import logging
from db import insert_behavioral_event, insert_conversation_message

from ..utils import get_recent_conversation_history, get_last_user_message
from ..prompts import CRISIS_MANAGEMENT_PROMPT

logger = logging.getLogger(__name__)

# Crisis indicators patterns
CRISIS_INDICATORS = {
    'suicide': ['suicide', 'kill myself', 'end my life', 'take my life', 'want to die', 'better off dead'],
    'self_harm': ['hurt myself', 'self harm', 'cut myself', 'harm myself', 'injure myself'],
    'hopelessness': ['no point', 'worthless', 'give up', 'can\'t go on'],
    'imminent_danger': ['right now', 'tonight', 'today', 'immediately', 'have a plan']
}

EMERGENCY_RESOURCES = """
**Immediate Crisis Resources:**
• **National Suicide Prevention Lifeline**: 988 or 1-800-273-8255
• **Crisis Text Line**: Text HOME to 741741
• **Emergency Services**: 911
• **SAMHSA National Helpline**: 1-800-662-4357

If you're in immediate danger, please contact emergency services or go to your nearest emergency room.
"""

def detect_crisis_level(message: str) -> tuple[bool, str]:
    """
    Detect crisis indicators and assess risk level.
    Returns: (crisis_detected, risk_level)
    """
    message_lower = message.lower()
    
    # Check for imminent danger indicators
    suicide_found = any(indicator in message_lower for indicator in CRISIS_INDICATORS['suicide'])
    self_harm_found = any(indicator in message_lower for indicator in CRISIS_INDICATORS['self_harm'])
    hopelessness_found = any(indicator in message_lower for indicator in CRISIS_INDICATORS['hopelessness'])
    imminent_found = any(indicator in message_lower for indicator in CRISIS_INDICATORS['imminent_danger'])
    
    if (suicide_found or self_harm_found) and imminent_found:
        return True, 'imminent'
    elif suicide_found or self_harm_found:
        return True, 'high'
    elif hopelessness_found:
        return True, 'moderate'
    
    return False, 'low'

def crisis_management_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Crisis Management Agent - monitors for crisis indicators and provides appropriate interventions.
    """
    try:
        # Extract current user message and conversation history
        user_message = get_last_user_message(state["messages"])
        conversation_history = get_recent_conversation_history(state["messages"])
        user_context = state.get("user_context", "")
        
        # Detect crisis level
        crisis_detected, risk_level = detect_crisis_level(user_message)
        
        logger.info(f"Crisis detection: {crisis_detected}, Risk level: {risk_level}")
        
        # Initialize LLM
        llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            temperature=0.1  # Low temperature for consistent crisis responses
        )
        
        # Create prompt template
        prompt_template = ChatPromptTemplate.from_template(CRISIS_MANAGEMENT_PROMPT)
        
        # Prepare crisis-specific context
        crisis_context = {
            'crisis_detected': crisis_detected,
            'risk_level': risk_level,
            'emergency_resources': EMERGENCY_RESOURCES if crisis_detected else "",
            'safety_priority': "IMMEDIATE SAFETY IS THE TOP PRIORITY" if risk_level in ['high', 'imminent'] else ""
        }
        
        # Format the prompt
        formatted_prompt = prompt_template.format(
            user_context=user_context,
            conversation_history=conversation_history,
            user_message=user_message,
            crisis_detected=crisis_context['crisis_detected'],
            risk_level=crisis_context['risk_level'],
            emergency_resources=crisis_context['emergency_resources'],
            safety_priority=crisis_context['safety_priority']
        )
        
        # Generate response
        response = llm.invoke([{"role": "user", "content": formatted_prompt}])
        
        # Create appropriate response based on risk level
        if risk_level == 'imminent':
            crisis_response = f"""I'm very concerned about your safety right now. Your wellbeing is the most important thing.

{EMERGENCY_RESOURCES}

{response.content}

**This conversation has been flagged for immediate clinical review.**"""
            
        elif risk_level == 'high':
            crisis_response = f"""I hear that you're going through an extremely difficult time, and I want you to know that help is available.

{EMERGENCY_RESOURCES}

{response.content}

**A mental health professional will be notified to provide additional support.**"""
            
        elif risk_level == 'moderate':
            crisis_response = f"""{response.content}

If you ever feel like you might hurt yourself or others, please reach out for help:
• **National Suicide Prevention Lifeline**: 988
• **Crisis Text Line**: Text HOME to 741741"""
            
        else:
            crisis_response = response.content
        
        # Create AI message with crisis metadata
        ai_message = AIMessage(
            content=crisis_response,
            additional_kwargs={
                "crisis_detected": crisis_detected,
                "risk_level": risk_level,
                "requires_escalation": risk_level in ['high', 'imminent'],
                "agent": "crisis_management"
            }
        )
        
        # Log crisis events
        if crisis_detected:
            logger.warning(f"Crisis detected - Risk level: {risk_level}, User message: {user_message[:100]}...")
            # Fire-and-forget behavioral event logging (async not awaited since function is sync)
            try:  # best effort
                import asyncio
                auth_user = state.get("extra_state", {}).get("auth_user") or {}
                user_id = auth_user.get("id")
                session_token = state.get("extra_state", {}).get("auth_user", {}).get("token")
                asyncio.create_task(
                    insert_behavioral_event(
                        user_id,
                        "crisis_flag",
                        text_value=risk_level,
                        tags=[risk_level],
                        metadata={"agent": "crisis_management", "crisis_detected": True},
                        session_token=session_token,
                    )
                )
            except Exception:
                pass
        
        return {"messages": state["messages"] + [ai_message]}
        
    except Exception as e:
        logger.error(f"Error in crisis management agent: {str(e)}")
        
        # Fallback safe response
        fallback_response = f"""I want to make sure you're safe. If you're having thoughts of hurting yourself or others, please reach out for immediate help:

{EMERGENCY_RESOURCES}

I'm here to support you, and there are trained professionals available 24/7."""
        
        ai_message = AIMessage(
            content=fallback_response,
            additional_kwargs={
                "crisis_detected": True,
                "risk_level": "unknown",
                "requires_escalation": True,
                "agent": "crisis_management",
                "error": "fallback_activated"
            }
        )
        
        try:  # Log AI response message metadata
            import asyncio
            auth_user = state.get("extra_state", {}).get("auth_user") or {}
            user_id = auth_user.get("id")
            session_token = state.get("extra_state", {}).get("auth_user", {}).get("token")
            asyncio.create_task(
                insert_conversation_message(
                    user_id,
                    role="agent",
                    content=ai_message.content,
                    intent="crisis_intervention" if crisis_detected else None,
                    metadata={"risk_level": risk_level, "agent": "crisis_management"},
                    session_token=session_token,
                )
            )
        except Exception:
            pass
        return {"messages": state["messages"] + [ai_message]}