function renderFormattedText(text) {
    if (!text) return null;

    // Split paragraphs by double newlines
    const paragraphs = text.split(/\n\n+/);

    return paragraphs.map((para, pIdx) => {
        const lines = para.split('\n');

        // Check if paragraph is a list
        const isBulletList = lines.every((line) => line.trim().startsWith('•') || line.trim().startsWith('-'));

        if (isBulletList) {
            return (
                <ul key={pIdx} className="bubble-list">
                    {lines.map((line, lIdx) => {
                        const cleanLine = line.replace(/^[•\-]\s*/, '');
                        return <li key={lIdx}>{formatInline(cleanLine)}</li>;
                    })}
                </ul>
            );
        }

        return (
            <p key={pIdx} className="bubble-para">
                {lines.map((line, lIdx) => (
                    <span key={lIdx}>
                        {formatInline(line)}
                        {lIdx < lines.length - 1 && <br />}
                    </span>
                ))}
            </p>
        );
    });
}

function formatInline(str) {
    // Replace **bold** with <strong>
    const parts = [];
    const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
    let lastIdx = 0;
    let match;

    while ((match = regex.exec(str)) !== null) {
        if (match.index > lastIdx) {
            parts.push(str.substring(lastIdx, match.index));
        }
        const m = match[0];
        if (m.startsWith('**') && m.endsWith('**')) {
            parts.push(<strong key={match.index}>{m.slice(2, -2)}</strong>);
        } else if (m.startsWith('`') && m.endsWith('`')) {
            parts.push(<code key={match.index} className="inline-code">{m.slice(1, -1)}</code>);
        }
        lastIdx = regex.lastIndex;
    }

    if (lastIdx < str.length) {
        parts.push(str.substring(lastIdx));
    }

    return parts.length > 0 ? parts : str;
}

export default function MessageBubble({ message, onSelectAction }) {
    const isUser = message.role === 'user';
    const visualItems = message.visual_items || [];
    const options = message.options || [];

    return (
        <div className={`row ${isUser ? 'row--user' : 'row--ai'}`}>
            {!isUser && (
                <div className="ai-avatar" title="Return Assistant">
                    <span>✦</span>
                </div>
            )}

            <div className={`bubble ${isUser ? 'bubble--user' : 'bubble--ai'}`}>
                <span className="sr-only">{isUser ? 'You said: ' : 'Assistant said: '}</span>
                
                <div className="bubble__content">
                    {renderFormattedText(message.content)}
                </div>

                {/* Visual item cards for order return selection */}
                {visualItems.length > 0 && (
                    <div className="visual-items-container">
                        <div className="visual-items-grid">
                            {visualItems.map((item) => (
                                <div key={item.order_item_id || item.index} className="visual-card">
                                    <div className="visual-card__top">
                                        <span className="visual-card__badge">Option #{item.index}</span>
                                        <span className="visual-card__tag">
                                            {item.return_window_days ? `${item.return_window_days}-day return` : 'Eligible'}
                                        </span>
                                    </div>
                                    <div className="visual-card__info">
                                        <h4 className="visual-card__name">{item.product_name}</h4>
                                        <p className="visual-card__meta">
                                            {item.brand && <span>{item.brand} • </span>}
                                            {item.category && <span>{item.category}</span>}
                                        </p>
                                        <div className="visual-card__details">
                                            <span>Order: <strong>{item.order_id}</strong></span>
                                            <span>Delivered: {item.delivery_date}</span>
                                        </div>
                                        <div className="visual-card__price">
                                            ₹{Number(item.price || 0).toLocaleString('en-IN')}
                                        </div>
                                    </div>
                                    <button
                                        type="button"
                                        className="btn btn--primary visual-card__select-btn"
                                        onClick={() => onSelectAction && onSelectAction(String(item.index))}
                                    >
                                        Return This Item (#{item.index})
                                    </button>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Quick selection chips for reasons / refund methods / confirmation */}
                {options.length > 0 && (
                    <div className="quick-options-row">
                        {options.map((opt) => (
                            <button
                                key={opt.value}
                                type="button"
                                className={`btn ${opt.value === 'YES' ? 'btn--success' : opt.value === 'NO' ? 'btn--danger' : 'btn--chip'}`}
                                onClick={() => onSelectAction && onSelectAction(opt.value)}
                            >
                                {opt.label}
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
