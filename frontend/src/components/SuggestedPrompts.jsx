const PROMPTS = [
    'Can you help me return an item?',
    'Can you help me return the shoes I ordered last week?',
    'What is your return policy?',
    'Show my recent orders',
];

export default function SuggestedPrompts({ onSelect }) {
    return (
        <div className="chips">
            {PROMPTS.map((p) => (
                <button key={p} type="button" className="chip" onClick={() => onSelect(p)}>
                    {p}
                </button>
            ))}
        </div>
    );
}
