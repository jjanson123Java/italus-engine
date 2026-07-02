def generate_with_claude(prompt: str) -> str:
    """
    Claude provider adapter.

    Temporary test harness for now.

    Current behavior:
    - returns the prompt unchanged so the engine pipeline can be validated

    Future behavior:
    - send the prompt to the Claude API
    - return generated prose and/or structured result payload
    """
    return prompt