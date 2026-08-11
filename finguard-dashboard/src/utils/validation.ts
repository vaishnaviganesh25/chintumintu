import type { TransactionInput, ValidationErrors } from '../types';

/**
 * Validates VPA format (must contain "@" symbol)
 */
export function validateVPA(vpa: string): boolean {
  return vpa.trim().length > 0 && vpa.includes('@');
}

/**
 * Validates amount (must be positive number)
 */
export function validateAmount(amount: string): boolean {
  const trimmed = amount.trim();
  if (trimmed === '') return false;
  
  const num = Number(trimmed);
  // Check if it's a valid number and positive
  // Number() is stricter than parseFloat() - it rejects "10abc"
  return !isNaN(num) && num > 0 && isFinite(num);
}

/**
 * Validates the optional receiver VPA age.
 *
 * Blank is valid - the field is optional and the backend applies its own default.
 * Anything present must be a whole number of days inside the range the model was
 * trained on, matching the API's own 0-1000 bound so the error surfaces here rather
 * than as a 422 round trip.
 */
export function validateVpaAge(age: string): boolean {
  const trimmed = age.trim();
  if (trimmed === '') return true;

  const num = Number(trimmed);
  return Number.isInteger(num) && num >= 0 && num <= 1000;
}

/**
 * Validates complete transaction input
 */
export function validateTransactionInput(
  input: Partial<TransactionInput> & { amount: number | string }
): ValidationErrors {
  const errors: ValidationErrors = {};

  if (input.senderVPA !== undefined && !validateVPA(input.senderVPA)) {
    errors.senderVPA = 'Sender VPA must contain @ symbol (e.g., user@ybl)';
  }

  if (input.receiverVPA !== undefined && !validateVPA(input.receiverVPA)) {
    errors.receiverVPA =
      'Receiver VPA must contain @ symbol (e.g., merchant@paytm)';
  }

  if (
    input.amount !== undefined &&
    !validateAmount(input.amount.toString())
  ) {
    errors.amount = 'Amount must be a positive number';
  }

  return errors;
}
