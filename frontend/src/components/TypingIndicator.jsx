export default function TypingIndicator() {
    return (
        <div className="row row--ai">
            <div className="bubble bubble--ai typing" role="status" aria-label="Assistant is typing">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
            </div>
        </div>
    );
}