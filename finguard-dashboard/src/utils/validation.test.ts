import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import {
  validateVPA,
  validateAmount,
  validateTransactionInput,
  validateVpaAge,
  validateTimestamp,
  validateGapSeconds,
} from './validation';

describe('validation utilities', () => {
  describe('validateVPA', () => {
    it('should return true for valid VPA with @ symbol', () => {
      expect(validateVPA('user@ybl')).toBe(true);
      expect(validateVPA('merchant@paytm')).toBe(true);
    });

    it('should return false for VPA without @ symbol', () => {
      expect(validateVPA('userybl')).toBe(false);
      expect(validateVPA('merchant')).toBe(false);
    });

    it('should return false for empty VPA', () => {
      expect(validateVPA('')).toBe(false);
      expect(validateVPA('   ')).toBe(false);
    });
  });

  describe('validateAmount', () => {
    it('should return true for positive numbers', () => {
      expect(validateAmount('100')).toBe(true);
      expect(validateAmount('0.01')).toBe(true);
      expect(validateAmount('1000.50')).toBe(true);
    });

    it('should return false for zero or negative numbers', () => {
      expect(validateAmount('0')).toBe(false);
      expect(validateAmount('-10')).toBe(false);
      expect(validateAmount('-0.5')).toBe(false);
    });

    it('should return false for non-numeric strings', () => {
      expect(validateAmount('abc')).toBe(false);
      expect(validateAmount('')).toBe(false);
      expect(validateAmount('10abc')).toBe(false);
    });
  });

  describe('validateTransactionInput', () => {
    it('should return no errors for valid input', () => {
      const errors = validateTransactionInput({
        senderVPA: 'user@ybl',
        receiverVPA: 'merchant@paytm',
        amount: 100,
      });
      expect(Object.keys(errors).length).toBe(0);
    });

    it('should return errors for invalid VPAs', () => {
      const errors = validateTransactionInput({
        senderVPA: 'invalidvpa',
        receiverVPA: 'merchant@paytm',
        amount: 100,
      });
      expect(errors.senderVPA).toBeDefined();
    });

    it('should return errors for invalid amount', () => {
      const errors = validateTransactionInput({
        senderVPA: 'user@ybl',
        receiverVPA: 'merchant@paytm',
        amount: -10,
      });
      expect(errors.amount).toBeDefined();
    });
  });
});

// --------------------------------------------------------------------------- //
// Property-based coverage for the fields added alongside the timestamp fix.
//
// Example-based tests confirm the cases we thought of. These assert the rules that
// must hold across the whole input space - which is where a validator that is looser
// than the API's own Pydantic rules shows up, as a 422 the form should have caught.
// --------------------------------------------------------------------------- //
describe('validateTimestamp (properties)', () => {
  it('accepts every value an <input type="datetime-local"> can emit', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 2020, max: 2035 }),
        fc.integer({ min: 1, max: 12 }),
        fc.integer({ min: 1, max: 28 }),
        fc.integer({ min: 0, max: 23 }),
        fc.integer({ min: 0, max: 59 }),
        (y, mo, d, h, mi) => {
          const pad = (n: number) => String(n).padStart(2, '0');
          const value = `${y}-${pad(mo)}-${pad(d)}T${pad(h)}:${pad(mi)}`;
          expect(validateTimestamp(value)).toBe(true);
        },
      ),
      { numRuns: 200 },
    );
  });

  it('treats blank and whitespace as "use the server clock"', () => {
    fc.assert(
      fc.property(fc.stringMatching(/^[ \t]*$/), (blank) => {
        expect(validateTimestamp(blank)).toBe(true);
      }),
      { numRuns: 50 },
    );
  });

  it('rejects text that does not parse as a date', () => {
    for (const junk of [
      'not-a-date',
      '2026-13-45T99:99',
      'yesterday',
      '2026-08-',        // Date parses this as 1 August - shape check catches it
      '2026-08-23',      // a date with no time is not a transaction time
      '2026-02-31T10:00' // parses, but rolls over to 3 March
    ]) {
      expect(validateTimestamp(junk)).toBe(false);
    }
  });
});

describe('validateGapSeconds (properties)', () => {
  it('accepts any finite value at or above the -1 sentinel', () => {
    fc.assert(
      fc.property(fc.float({ min: -1, max: 1_000_000, noNaN: true }), (gap) => {
        expect(validateGapSeconds(String(gap))).toBe(true);
      }),
      { numRuns: 200 },
    );
  });

  it('rejects anything below -1, which is not a documented encoding', () => {
    fc.assert(
      fc.property(fc.float({ min: -1_000_000, max: Math.fround(-1.01), noNaN: true }), (gap) => {
        expect(validateGapSeconds(String(gap))).toBe(false);
      }),
      { numRuns: 100 },
    );
  });

  it('rejects non-numeric text', () => {
    for (const junk of ['soon', '10s', '--5', 'NaN', 'Infinity']) {
      expect(validateGapSeconds(junk)).toBe(false);
    }
  });
});

describe('validateVpaAge (properties)', () => {
  it('accepts exactly the range the API accepts', () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 1000 }), (age) => {
        expect(validateVpaAge(String(age))).toBe(true);
      }),
      { numRuns: 200 },
    );
  });

  it('rejects values outside it, so the error surfaces here not as a 422', () => {
    fc.assert(
      fc.property(
        fc.oneof(fc.integer({ min: -10_000, max: -1 }), fc.integer({ min: 1001, max: 10_000 })),
        (age) => {
          expect(validateVpaAge(String(age))).toBe(false);
        },
      ),
      { numRuns: 200 },
    );
  });

  it('rejects fractional days - an account age is a whole number', () => {
    for (const junk of ['1.5', '0.1', '99.999']) {
      expect(validateVpaAge(junk)).toBe(false);
    }
  });
});
