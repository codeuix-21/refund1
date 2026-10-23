import { useRef, useState } from 'react';

export default function Composer({ onSend, disabled }) {
    const [text, setText] = useState('');
    const ref = useRef(null);

    function resize() {
        const el = ref.current;
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
    }

    function submit() {
        if (!text.trim() || disabled) return;
        onSend(text);
        setText('');
        requestAnimationFrame(() => {
            if (ref.current) ref.current.style.height = 'auto';
        });
    }

    function handleKeyDown(e) {
        if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
        }
    }

    return (
        <form
            className="composer"
            onSubmit={(e) => {
                e.preventDefault();
                submit();
            }}
        >
            <label htmlFor="chat-input" className="sr-only">
                Type your message
            </label>
            <textarea
                id="chat-input"
                ref={ref}
                className="composer__input"
                rows={1}
                placeholder="Type your message…"
                value={text}
                onChange={(e) => {
                    setText(e.target.value);
                    resize();
                }}
                onKeyDown={handleKeyDown}
            />
            <button
                type="submit"
                className="btn btn--primary"
                disabled={disabled || !text.trim()}
                aria-label="Send message"
            >
                Send
            </button>
        </form>
    );
}