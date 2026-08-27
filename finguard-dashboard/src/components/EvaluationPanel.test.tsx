import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { EvaluationPanel } from './EvaluationPanel';
import type { FraudDetectionResponse } from '../types';

/**
 * These cover the three things the panel gets wrong silently — a wrong number, a label
 * pointing at the wrong place, and a verdict that contradicts the costs beside it. All
 * three render without erroring, so nothing but an assertion catches them.
 */

const base: FraudDetectionResponse = {
  transaction_id: 'tx-1',
  action: 'HOLD',
  action_costs: { ACCEPT: 63243, STEP_UP: 9487, HOLD: 151 },
  status: 'BLOCKED',
  fraud_probability: 0.687,
  execution_time_ms: 148,
  xai_explanation: '',
  shap_features: [],
  network_reasons: [],
};

const show = (r: Partial<FraudDetectionResponse>, threshold: number | null = 0.268) =>
  render(<EvaluationPanel isLoading={false} results={{ ...base, ...r }} threshold={threshold} />);

/** The cost table alone — the verdict block above it repeats the action name. */
const costSection = () =>
  screen.getByText('What each action would cost').closest('section') as HTMLElement;

describe('risk readout', () => {
  it('never claims 100%, however the probability rounds', () => {
    show({ fraud_probability: 0.99973 });
    expect(screen.getByText('>99.9%')).toBeInTheDocument();
    expect(screen.queryByText('100.0%')).not.toBeInTheDocument();
  });

  it('never claims 0% for a nonzero probability', () => {
    show({ fraud_probability: 0.00002 });
    expect(screen.getByText('<0.1%')).toBeInTheDocument();
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument();
  });

  it('reports an ordinary probability verbatim', () => {
    show({ fraud_probability: 0.687 });
    expect(screen.getByText('68.7%')).toBeInTheDocument();
  });

  it('anchors the threshold caption to the notch it describes', () => {
    // The bug this replaces: the caption sat at the 50% mark of a space-between row
    // while naming a threshold at 26.8%.
    show({}, 0.268);
    const caption = screen.getByText(/calibrated cut-off 26\.8%/);
    expect(parseFloat(caption.style.left)).toBeCloseTo(26.8, 5);
  });

  it('does not call the cut-off a hold line', () => {
    // It governs the legacy block/allow `status`, not the action — and STEP_UP lands
    // above it often enough that "holds at X%" contradicted the verdict on screen.
    show({ action: 'STEP_UP', fraud_probability: 0.335 }, 0.268);
    expect(screen.queryByText(/holds at/)).not.toBeInTheDocument();
  });

  it('omits the caption when the server reports no threshold', () => {
    show({}, null);
    expect(screen.queryByText(/cut-off/)).not.toBeInTheDocument();
  });
});

describe('cost comparison', () => {
  it('orders the actions cheapest first and marks the one taken', () => {
    show({ action: 'HOLD' });
    const labels = within(costSection())
      .getAllByRole('listitem')
      .map((row) => within(row).getByText(/^(ACCEPT|CHALLENGE|HOLD)$/).textContent);
    expect(labels).toEqual(['HOLD', 'CHALLENGE', 'ACCEPT']);
    expect(screen.getByText('TAKEN')).toBeInTheDocument();
  });

  it('states the saving when the cheapest action was taken', () => {
    show({ action: 'HOLD' });
    expect(screen.getByText(/9,336 below the next best/)).toBeInTheDocument();
    expect(screen.queryByText(/Escalated past/)).not.toBeInTheDocument();
  });

  it('explains itself when a cheaper action was passed over', () => {
    // Cross-merchant reputation legitimately escalates past price. Rendering the costs
    // without the reason is what made a working policy read as a defect.
    // CHALLENGE is dearer than HOLD here, so price alone would not have chosen it.
    show({
      action: 'STEP_UP',
      network_reasons: ['this payer was confirmed fraudulent at another merchant'],
    });
    expect(screen.getByText(/Escalated past the cheapest action/)).toBeInTheDocument();
    expect(
      screen.getByText(/this payer was confirmed fraudulent at another merchant/),
    ).toBeInTheDocument();
  });

  it('surfaces network evidence even when it did not reorder the prices', () => {
    // HOLD was already cheapest, so nothing looks contradictory — but the evidence still
    // fired, and it is part of why this payment was held.
    show({ action: 'HOLD', network_reasons: ['seen at two other merchants today'] });
    expect(screen.getByText('Cross-merchant evidence.')).toBeInTheDocument();
    expect(screen.getByText(/seen at two other merchants today/)).toBeInTheDocument();
    expect(screen.queryByText(/Escalated past/)).not.toBeInTheDocument();
  });

  it('stays quiet when no evidence fired and price picked the action', () => {
    show({ action: 'HOLD', network_reasons: [] });
    expect(screen.queryByText(/Cross-merchant evidence|Escalated past/)).not.toBeInTheDocument();
  });

  it('quantifies what the escalation cost', () => {
    show({ action: 'ACCEPT' });
    expect(screen.getByText(/63,092 more/)).toBeInTheDocument();
    expect(screen.getByText(/than HOLD, which was the cheapest/)).toBeInTheDocument();
  });

  it('colours only the taken bar, so length never reads as approval', () => {
    // A full-width ACCEPT-green bar on the most expensive option was the defect: long
    // and green reads as "good" regardless of the figure beside it.
    show({ action: 'HOLD' });
    const fills = Array.from(
      costSection().querySelectorAll<HTMLElement>('div[style*="height: 100%"]'),
    );
    const coloured = fills.filter((f) => /--(accept|challenge|hold)-fill/.test(f.style.background));
    expect(coloured).toHaveLength(1);
  });
});

describe('the two policies', () => {
  it('reports settlement from the action, not the legacy threshold call', () => {
    // A challenged payment scoring under the cut-off used to announce itself as
    // "settled" because `status` was APPROVED. A 3-D Secure challenge is not settled.
    show({ action: 'STEP_UP', status: 'APPROVED', fraud_probability: 0.2 });
    expect(screen.getByText('settles once the challenge clears')).toBeInTheDocument();
    expect(screen.queryByText(/^settled$/)).not.toBeInTheDocument();
  });

  it('says so when the cut-off and the cost comparison disagree', () => {
    show({ action: 'STEP_UP', status: 'BLOCKED', fraud_probability: 0.335 }, 0.268);
    expect(screen.getByText(/A single cut-off at 26\.8% would have/)).toBeInTheDocument();
    expect(screen.getByText('blocked')).toBeInTheDocument();
  });

  it('stays quiet when the two policies agree', () => {
    show({ action: 'HOLD', status: 'BLOCKED', fraud_probability: 0.9 }, 0.268);
    expect(screen.queryByText(/A single cut-off/)).not.toBeInTheDocument();
  });

  it('flags a payment the cut-off would have allowed but price held', () => {
    show({ action: 'HOLD', status: 'APPROVED', fraud_probability: 0.2 }, 0.268);
    expect(screen.getByText('allowed')).toBeInTheDocument();
  });
});

describe('degradation', () => {
  it('names the rung when something other than the full model answered', () => {
    show({ rung: 'rules only' });
    expect(screen.getByText('rules only')).toBeInTheDocument();
  });

  it('stays quiet when the full model answered', () => {
    show({ rung: 'full model' });
    expect(screen.queryByText('full model')).not.toBeInTheDocument();
  });

  it('shows the ledger id so a decision can be replayed later', () => {
    show({ decision_id: 'dec-abc123' });
    const meta = screen.getByText('dec-abc123');
    expect(within(meta.parentElement as HTMLElement).getByText('148 ms')).toBeInTheDocument();
  });
});
