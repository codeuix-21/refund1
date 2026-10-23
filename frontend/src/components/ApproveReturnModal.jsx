import { useEffect, useRef } from 'react';

const METHOD_LABELS = { BANK_CARD: 'Refund to card', STORE_CREDIT: 'Store Credit' };
const REASON_LABELS = {
    DEFECTIVE: 'Defective',
    WRONG_ITEM: 'Wrong item received',
    DAMAGED: 'Damaged',
    SIZE_ISSUE: 'Size issue',
    NOT_AS_EXPECTED: 'Not as expected',
    OTHER: 'Other',
};

function formatRupees(paise) {
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(paise / 100);
}

export default function ApproveReturnModal({ open, details, onApprove, onCancel }) {
    const dialogRef = useRef(null);
    const cancelRef = useRef(null);
    const cancelHandler = useRef(onCancel);
    cancelHandler.current = onCancel;

    useEffect(() => {
        if (!open) return undefined;
        const previouslyFocused = document.activeElement;
        cancelRef.current?.focus(); // safest default: Cancel

        function onKeyDown(e) {
            if (e.key === 'Escape') {
                cancelHandler.current();
                return;
            }
            if (e.key !== 'Tab') return;
            const buttons = dialogRef.current?.querySelectorAll('button');
            if (!buttons || buttons.length === 0) return;
            const first = buttons[0];
            const last = buttons[buttons.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }

        document.addEventListener('keydown', onKeyDown);
        return () => {
            document.removeEventListener('keydown', onKeyDown);
            previouslyFocused?.focus?.();
        };
    }, [open]);

    if (!open || !details) return null;

    return (
        <div className="modal-overlay" onClick={onCancel}>
            <div
                ref={dialogRef}
                className="modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="approve-title"
                onClick={(e) => e.stopPropagation()}
            >
                <h2 id="approve-title" className="modal__title">Approve this return?</h2>
                <p className="modal__note">
                    Please check the details. Nothing is booked until you approve.
                    <strong> Demo only: no real return or refund is created.</strong>
                </p>

                <dl className="modal__list">
                    <div><dt>Item</dt><dd>{details.itemName}</dd></div>
                    <div><dt>Reason</dt><dd>{REASON_LABELS[details.reason] ?? details.reason}</dd></div>
                    <div><dt>Pickup address</dt><dd>{details.pickupAddress}</dd></div>
                    <div><dt>Refund method</dt><dd>{METHOD_LABELS[details.refundMethod] ?? details.refundMethod}</dd></div>
                    <div><dt>Refund amount</dt><dd>{formatRupees(details.refundAmountPaise)}</dd></div>
                </dl>

                <div className="modal__actions">
                    <button ref={cancelRef} type="button" className="btn btn--ghost btn--big" onClick={onCancel}>
                        Cancel
                    </button>
                    <button type="button" className="btn btn--primary btn--big" onClick={onApprove}>
                        Approve
                    </button>
                </div>
            </div>
        </div>
    );
}