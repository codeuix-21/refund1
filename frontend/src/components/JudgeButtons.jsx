import { useEffect, useRef, useState } from 'react';
import { SCENARIOS } from '../services/judgeScenarios.js';

export default function JudgeButtons({
    onRun,
    disabled,
    activeId,
    demoStep,
    onBack,
    onNext,
    onPreview,
}) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);

    // Close on outside click or Escape
    useEffect(() => {
        if (!open) return;
        const onDown = (e) => {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        };
        const onKey = (e) => {
            if (e.key === 'Escape') setOpen(false);
        };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [open]);

    // Run an action, then close the menu
    const act = (fn) => (...args) => {
        fn(...args);
        setOpen(false);
    };

    return (
        <details ref={ref} className="demo-tools" open={open}>
            <summary
                className="btn btn--ghost btn--small-ghost"
                onClick={(e) => {
                    e.preventDefault();
                    setOpen((o) => !o);
                }}
            >
                Demo tools
            </summary>
            <div className="demo-menu">
                <p className="demo-menu__label">Quick tests (simulated)</p>
                <div className="demo-menu__list">
                    {SCENARIOS.map((s) => (
                        <button
                            key={s.id}
                            type="button"
                            className={`judge__btn ${activeId === s.id ? 'judge__btn--active' : ''}`}
                            onClick={() => act(onRun)(s)}
                            disabled={disabled}
                            aria-pressed={activeId === s.id}
                        >
                            {s.label}
                        </button>
                    ))}
                </div>

                <p className="demo-menu__label">Refund progress (demo only)</p>
                <div className="demo-menu__row">
                    <button
                        type="button"
                        className="btn btn--ghost btn--small-ghost"
                        onClick={act(onBack)}
                        disabled={demoStep === 0}
                    >
                        Back
                    </button>
                    <button
                        type="button"
                        className="btn btn--ghost btn--small-ghost"
                        onClick={act(onPreview)}
                    >
                        Preview approval popup
                    </button>
                    <button
                        type="button"
                        className="btn btn--ghost btn--small-ghost"
                        onClick={act(onNext)}
                        disabled={demoStep === 5}
                    >
                        Next step
                    </button>
                </div>
            </div>
        </details>
    );
}
