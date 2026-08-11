import { describe, it, expect } from 'vitest';
import { validateVPA, validateAmount, validateTransactionInput } from './validation';

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
