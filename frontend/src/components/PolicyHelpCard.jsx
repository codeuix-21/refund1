export default function PolicyHelpCard() {
    return (
        <section className="card policy-card" aria-label="Return Policy & Help">
            <h2 className="card__title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>🛡️</span> Store Return Policy
            </h2>
            <div className="policy-list">
                <div className="policy-item">
                    <span className="policy-item__icon">📅</span>
                    <div>
                        <strong>7 to 14-Day Window</strong>
                        <p>Most items are eligible for return within 7–14 days of delivery.</p>
                    </div>
                </div>
                <div className="policy-item">
                    <span className="policy-item__icon">🚚</span>
                    <div>
                        <strong>Free Doorstep Pickup</strong>
                        <p>Our courier picks up the package right from your doorstep.</p>
                    </div>
                </div>
                <div className="policy-item">
                    <span className="policy-item__icon">⚡</span>
                    <div>
                        <strong>Direct Bank Credit</strong>
                        <p>Refunds are credited to your original payment card or store credit.</p>
                    </div>
                </div>
                <div className="policy-item">
                    <span className="policy-item__icon">✨</span>
                    <div>
                        <strong>No Receipt Needed</strong>
                        <p>Your order history is automatically synced with our assistant.</p>
                    </div>
                </div>
            </div>
        </section>
    );
}
