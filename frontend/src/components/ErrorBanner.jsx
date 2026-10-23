export default function ErrorBanner({ message, onRetry }) {
    return (
        <div className="error" role="alert">
            <span>{message}</span>
            <button type="button" className="btn btn--small" onClick={onRetry}>
                Retry
            </button>
        </div>
    );
}