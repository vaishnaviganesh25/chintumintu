import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { XAIPanel } from './XAIPanel';

/**
 * A citation is the one piece of UI copy where being approximately right is worse than
 * being absent — a reader who checks a reference and finds it does not say what the
 * panel claimed trusts nothing else on the screen. Both of these were verified against
 * the published record; these tests keep a later edit from quietly drifting off them.
 */

const method = () => screen.getByText('Method').closest('footer') as HTMLElement;

describe('method and sources', () => {
  it('cites its sources before any payment has been scored', () => {
    // The point of the section is that the panel can be checked *before* you trust
    // anything it says, so it is not gated behind having data.
    render(<XAIPanel explanation={null} shapFeatures={null} />);
    expect(method()).toBeInTheDocument();
  });

  it('links the SHAP and TreeSHAP papers at their verified identifiers', () => {
    render(<XAIPanel explanation="held" shapFeatures={null} />);
    const links = within(method()).getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      'https://arxiv.org/abs/1705.07874', // Lundberg & Lee, NeurIPS 2017
      'https://arxiv.org/abs/1905.04610', // Lundberg et al., Nature Mach Intell 2020
    ]);
  });

  it('names the venue for each reference', () => {
    render(<XAIPanel explanation="held" shapFeatures={null} />);
    const footer = within(method());
    expect(footer.getByText(/Advances in Neural Information Processing Systems 30/)).toBeInTheDocument();
    expect(footer.getByText(/Nature Machine Intelligence 2, 56–67/)).toBeInTheDocument();
  });

  it('opens references safely in a new tab', () => {
    // target=_blank without noopener hands the opened page a handle on this one.
    render(<XAIPanel explanation="held" shapFeatures={null} />);
    for (const a of within(method()).getAllByRole('link')) {
      expect(a).toHaveAttribute('target', '_blank');
      expect(a.getAttribute('rel')).toContain('noopener');
    }
  });

  it('describes TreeSHAP as exact rather than approximate', () => {
    // The distinction is the reason the citation is worth making: TreeSHAP computes
    // Shapley values exactly for trees, where the general case needs sampling.
    render(<XAIPanel explanation="held" shapFeatures={null} />);
    expect(within(method()).getByText(/exact polynomial-time algorithm/)).toBeInTheDocument();
  });
});
