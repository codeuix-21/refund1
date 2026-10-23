import { useEffect, useRef } from 'react';

const META = {
    thinking: { icon: '🧠', label: 'Thinking' },
    tool: { icon: '🔧', label: 'Tool called' },
    store: { icon: '📋', label: 'Store replied' },
};

function formatTime(iso) {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export default function ThoughtBox({ events, isLoading }) {
    const endRef = useRef(null);

    useEffect(() => {
        endRef.current?.scrollIntoView({ block: 'nearest' });
    }, [events, isLoading]);

    return (
        <details className="thoughts">
            <summary className="thoughts__summary">
                <span className="when-closed">Show</span>
                <span className="when-open">Hide</span>
                &nbsp;agent activity ({events.length})
            </summary>

            <ul className="thoughts__list" role="log" aria-label="Agent activity">
                {events.length === 0 && !isLoading && (
                    <li className="thoughts__empty">
                        Nothing yet. Send a message to see what the agent is thinking and which tools it uses.
                    </li>
                )}

                {events.map((e) => {
                    const meta = META[e.type] ?? { icon: '•', label: e.type };
                    return (
                        <li key={e.id} className={`thought thought--${e.type}`}>
                            <span className="thought__icon" aria-hidden="true">{meta.icon}</span>
                            <span className="thought__body">
                                <span className="thought__label">
                                    {meta.label} <time className="thought__time">{formatTime(e.timestamp)}</time>
                                </span>
                                <span className="thought__text">{e.text}</span>
                            </span>
                        </li>
                    );
                })}

                {isLoading && (
                    <li className="thought thought--thinking">
                        <span className="thought__icon" aria-hidden="true">🧠</span>
                        <span className="thought__body">
                            <span className="thought__text">Thinking…</span>
                        </span>
                    </li>
                )}
                <li ref={endRef} aria-hidden="true" />
            </ul>
        </details>
    );
}
