import { useState, useEffect } from 'react';
import { fetchRefunds } from '../services/chatService.js';

const STEPS = [
    { key: 'REQUESTED', label: '1. Requested', hint: 'Return filed' },
    { key: 'PICKUP', label: '2. Pickup Booked', hint: 'Courier assigned' },
    { key: 'WAREHOUSE', label: '3. Quality Check', hint: 'Warehouse verification' },
    { key: 'INITIATED', label: '4. Refund Initiated', hint: 'Gateway transfer' },
    { key: 'CREDITED', label: '5. Bank Credit', hint: 'Funds deposited' },
];

export default function RefundStatusPage({ customerId = 'CUS-001' }) {
    const [refunds, setRefunds] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    async function load(isSilent = false) {
        if (!isSilent) setLoading(true);
        try {
            const data = await fetchRefunds(customerId);
            setRefunds(data.refunds || []);
            setError(null);
        } catch (err) {
            if (!isSilent) setError(err.message || 'Failed to load refund status');
        } finally {
            if (!isSilent) setLoading(false);
        }
    }

    useEffect(() => {
        load();
        // Live auto-poll every 1.0 second to catch 3-second step changes smoothly
        const timer = setInterval(() => {
            load(true);
        }, 1000);
        return () => clearInterval(timer);
    }, [customerId]);

    return (
        <div className="store-page">
            <div className="store-page__header">
                <div>
                    <h2 className="store-page__title">Refund Status</h2>
                    <p className="store-page__sub">
                        Real-time return processing, courier pickups, and refund credits for <strong>Aarav Sharma</strong>.
                    </p>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span className="live-indicator">
                        <span className="live-dot" /> Live Auto-Sync (1s)
                    </span>
                    <button type="button" className="btn btn--secondary" onClick={() => load(false)}>
                        Refresh Now
                    </button>
                </div>
            </div>

            {error && (
                <div className="error-banner" style={{ marginBottom: '16px' }}>
                    <span>{error}</span>
                    <button type="button" className="btn btn--small" onClick={() => load(false)}>Retry</button>
                </div>
            )}

            {loading && refunds.length === 0 ? (
                <div className="store-page__loading">Loading refund records from store database...</div>
            ) : refunds.length === 0 ? (
                <div className="store-page__empty">
                    <p>No returns or refunds filed yet.</p>
                    <p style={{ color: 'var(--muted)', fontSize: '0.9rem' }}>
                        Switch to the Return Assistant tab and say &ldquo;I want to return the things that I ordered&rdquo; to file your first return!
                    </p>
                </div>
            ) : (
                <div className="refunds-list">
                    {refunds.map((item) => {
                        const step = item.step || 1;
                        const isCredited = item.refund?.status === 'CREDITED' || item.status === 'COMPLETED';
                        const progressPercent = Math.min(100, Math.max(0, ((step - 1) / 4) * 100));

                        return (
                            <div key={item.return_id} className={`refund-card ${isCredited ? 'refund-card--completed' : ''}`}>
                                <div className="refund-card__header">
                                    <div>
                                        <div className="refund-card__title-row">
                                            <h3 className="refund-card__title">{item.product_name}</h3>
                                            <span className={`pill ${isCredited ? 'pill--green' : 'pill--amber'}`}>
                                                {isCredited ? '✓ REFUND CREDITED' : `STAGE ${step}/5 IN PROGRESS`}
                                            </span>
                                        </div>
                                        <div className="refund-card__sub">
                                            <span>Return ID: <strong>{item.return_id}</strong></span>
                                            <span>Order: {item.order_id}</span>
                                            {item.reason && <span>Reason: {item.reason}</span>}
                                        </div>
                                    </div>

                                    <div className="refund-card__amount-box">
                                        <div className="refund-card__amount">
                                            ₹{(item.refund?.amount || 0).toLocaleString('en-IN')}
                                        </div>
                                        <div className="refund-card__method">
                                            {item.refund?.method === 'STORE_CREDIT' ? 'Store Credit' : 'Bank Card'}
                                        </div>
                                    </div>
                                </div>

                                {/* Dynamic 5-Step Stepper with Animated Progress Line */}
                                <div className="stepper-wrapper">
                                    <div className="stepper-progress-bg">
                                        <div
                                            className={`stepper-progress-fill ${isCredited ? 'stepper-progress-fill--complete' : ''}`}
                                            style={{ width: `${progressPercent}%` }}
                                        />
                                    </div>

                                    <div className="stepper">
                                        {STEPS.map((s, idx) => {
                                            const stepNum = idx + 1;
                                            const done = stepNum < step;
                                            const current = stepNum === step;

                                            return (
                                                <div
                                                    key={s.key}
                                                    className={`stepper__step ${done ? 'stepper__step--done' : current ? 'stepper__step--current' : 'stepper__step--pending'}`}
                                                >
                                                    <div className="stepper__circle">
                                                        {done ? '✓' : stepNum}
                                                    </div>
                                                    <div className="stepper__label">{s.label}</div>
                                                    <div className="stepper__hint">
                                                        {done ? 'Done' : current ? (stepNum === 5 ? 'Credited' : 'In progress') : s.hint}
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>

                                <div className="refund-card__footer">
                                    <div className="refund-card__timestamps">
                                        <span>Requested: {new Date(item.requested_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                                        {item.refund?.credited_at && (
                                            <span style={{ color: '#15803d', fontWeight: 600 }}>
                                                Credited: {new Date(item.refund.credited_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                            </span>
                                        )}
                                    </div>
                                    {item.pickup?.pickup_id && (
                                        <div className="refund-card__pickup-ref">
                                            Courier Ref: <code>{item.pickup.pickup_id}</code>
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
