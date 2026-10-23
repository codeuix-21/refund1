export const STEPS = [
  { key: 'REQUESTED', label: '1. Requested', hint: 'Return filed & approved' },
  { key: 'PICKUP_SCHEDULED', label: '2. Pickup Booked', hint: 'Courier assigned for doorstep pickup' },
  { key: 'RETURN_RECEIVED', label: '3. Quality Check', hint: 'Warehouse verification' },
  { key: 'REFUND_INITIATED', label: '4. Refund Initiated', hint: 'Payment gateway transfer started' },
  { key: 'REFUND_CREDITED', label: '5. Bank Credit', hint: 'Funds deposited in designated account' },
];

export default function RefundTimeline({ currentStep = 0 }) {
  const percent = currentStep === 0 ? 0 : Math.round((currentStep / 5) * 100);

  function getStepState(stepNum) {
    if (currentStep === 0) return 'pending';
    if (stepNum < currentStep) return 'done';
    if (stepNum === currentStep) return 'current';
    return 'pending';
  }

  function getStepStatusText(stepNum) {
    if (currentStep === 0) return 'Pending';
    if (stepNum < currentStep) return 'Done';
    if (stepNum === currentStep) {
      return stepNum === 5 ? 'Completed' : 'In progress';
    }
    return 'Pending';
  }

  return (
    <section className="card refund-timeline-card" aria-label="Refund progress">
      <div className="refund-timeline-header">
        <h2 className="card__title">Refund Progress</h2>
        {currentStep > 0 ? (
          <span className={`pill ${currentStep === 5 ? 'pill--green' : 'pill--blue'}`}>
            {currentStep === 5 ? '✓ 100% Credited' : `Step ${currentStep}/5 • ${percent}%`}
          </span>
        ) : (
          <span className="pill pill--muted">Waiting</span>
        )}
      </div>

      {/* Dynamic Progress Bar */}
      <div className="timeline-progress-track" title={`Refund Progress: ${percent}%`}>
        <div
          className={`timeline-progress-fill ${currentStep === 5 ? 'timeline-progress-fill--complete' : ''}`}
          style={{ width: `${percent}%` }}
        />
      </div>

      {currentStep === 0 ? (
        <div className="timeline-empty">
          <p>Awaiting return request.</p>
          <span>Confirm a return in chat to track the 5-step live refund progress.</span>
        </div>
      ) : (
        <ol className="tl">
          {STEPS.map((step, i) => {
            const stepNum = i + 1;
            const state = getStepState(stepNum);
            const isDone = state === 'done';
            const isCurrent = state === 'current';

            return (
              <li
                key={step.key}
                className={`tl__step ${isDone ? 'tl__step--reached' : ''} ${isCurrent ? 'tl__step--current' : ''}`}
                aria-current={isCurrent ? 'step' : undefined}
              >
                <span className="tl__dot">
                  {isDone ? '✓' : stepNum}
                </span>
                <span className="tl__text">
                  <span className="tl__label">{step.label}</span>
                  <span className="tl__state">{getStepStatusText(stepNum)}</span>
                  {(isDone || isCurrent) && step.hint && (
                    <span className="tl__hint">{step.hint}</span>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
