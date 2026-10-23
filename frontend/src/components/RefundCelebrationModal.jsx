import { useEffect, useRef } from 'react';

export default function RefundCelebrationModal({ open, details, onClose, onViewRefunds }) {
    const dialogRef = useRef(null);

    useEffect(() => {
        if (!open) return;
        function onKeyDown(e) {
            if (e.key === 'Escape') {
                onClose();
            }
        }
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [open, onClose]);

    if (!open || !details) return null;

    const amountFormatted = details.amount
        ? `₹${Number(details.amount).toLocaleString('en-IN')}`
        : '₹' + Number((details.amount_paise || 0) / 100).toLocaleString('en-IN');

    const destination = details.method === 'STORE_CREDIT'
        ? 'Instant Store Credit'
        : 'Designated Bank Account / Original Payment Method';

    return (
        <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
            <div className="modal celebration-modal" onClick={(e) => e.stopPropagation()} ref={dialogRef}>
                <div className="celebration-modal__icon">
                    🎉
                </div>

                <h2 className="celebration-modal__title">
                    Refund Credited Successfully!
                </h2>

                <p className="celebration-modal__subtitle">
                    Yes! Your refund has been verified and credited to your <strong>{destination}</strong>.
                </p>

                <div className="celebration-modal__box">
                    <div className="celebration-modal__row">
                        <span>Product</span>
                        <strong>{details.product_name || 'Returned Item'}</strong>
                    </div>
                    <div className="celebration-modal__row">
                        <span>Return ID</span>
                        <code>{details.return_id}</code>
                    </div>
                    <div className="celebration-modal__row">
                        <span>Refund Amount</span>
                        <strong className="celebration-modal__amount">{amountFormatted}</strong>
                    </div>
                    <div className="celebration-modal__row">
                        <span>Destination</span>
                        <span>{destination}</span>
                    </div>
                    <div className="celebration-modal__row">
                        <span>Status</span>
                        <span className="pill pill--green">CREDITED &amp; COMPLETED</span>
                    </div>
                </div>

                <div className="celebration-modal__actions">
                    <button
                        type="button"
                        className="btn btn--primary"
                        onClick={() => {
                            onClose();
                            if (onViewRefunds) onViewRefunds();
                        }}
                    >
                        View in Refund Status Page
                    </button>
                    <button
                        type="button"
                        className="btn btn--secondary"
                        onClick={onClose}
                    >
                        Close
                    </button>
                </div>
            </div>
        </div>
    );
}
