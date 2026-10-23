import { useEffect, useRef } from 'react';
import MessageBubble from './MessageBubble.jsx';
import TypingIndicator from './TypingIndicator.jsx';
import SuggestedPrompts from './SuggestedPrompts.jsx';

export default function MessageList({ messages, isLoading, onPrompt }) {
    const endRef = useRef(null);

    useEffect(() => {
        endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }, [messages, isLoading]);

    const isEmpty = messages.length === 0;

    return (
        <div className="messages" role="log" aria-live="polite" aria-label="Conversation">
            {isEmpty && (
                <div className="empty">
                    <div className="empty__icon" aria-hidden="true">💬</div>
                    <h2 className="empty__title">How can I help today?</h2>
                    <p className="empty__text">
                        Ask about returning an item, tracking an existing refund, or view your purchases.
                    </p>
                    <SuggestedPrompts onSelect={onPrompt} />
                </div>
            )}

            {messages.map((m) => (
                <MessageBubble key={m.id} message={m} onSelectAction={onPrompt} />
            ))}

            {isLoading && <TypingIndicator />}
            <div ref={endRef} />
        </div>
    );
}
