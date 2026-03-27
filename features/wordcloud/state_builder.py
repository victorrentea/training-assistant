"""Word cloud state builder — contributes wordcloud state to participant and host state messages."""
from core.state import state


def build_for_participant(pid: str) -> dict:
    return {
        "wordcloud_words": state.wordcloud_words,
        "wordcloud_word_order": state.wordcloud_word_order,
        "wordcloud_topic": state.wordcloud_topic,
    }


def build_for_host() -> dict:
    return {
        "wordcloud_words": state.wordcloud_words,
        "wordcloud_word_order": state.wordcloud_word_order,
        "wordcloud_topic": state.wordcloud_topic,
    }


from core.messaging import register_state_builder
register_state_builder("wordcloud", build_for_participant, build_for_host)
