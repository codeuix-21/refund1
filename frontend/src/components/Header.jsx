export default function Header({ onReset, canReset, isMock }) {
    return (
        <header className="header">
            <div>
                <h1 className="header__title">
                    Return &amp; Refund Chaser
                    {isMock && <span className="badge">Demo mode</span>}
                </h1>
                <p className="header__subtitle">
                    Your assisstant for return and refund queries.
                </p>
            </div>
            <button
                type="button"
                className="btn btn--ghost"
                onClick={onReset}
                disabled={!canReset}
            >
                New Chat
            </button>
        </header>
    );
}