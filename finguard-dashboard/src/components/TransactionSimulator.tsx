import { useState } from 'react';
import type { TransactionInput, ValidationErrors } from '../types';
import { validateVPA, validateAmount, validateVpaAge } from '../utils/validation';

interface TransactionSimulatorProps {
  onSimulate: (data: TransactionInput) => Promise<void>;
  isLoading: boolean;
}

export function TransactionSimulator({ onSimulate, isLoading }: TransactionSimulatorProps) {
  const [formData, setFormData] = useState({
    senderVPA: '',
    receiverVPA: '',
    amount: '',
    receiverVpaAgeDays: ''
  });
  const [errors, setErrors] = useState<ValidationErrors>({});

  const validateForm = () => {
    const newErrors: ValidationErrors = {};
    
    if (!validateVPA(formData.senderVPA)) {
      newErrors.senderVPA = 'Sender VPA must contain @ symbol (e.g., user@ybl)';
    }
    
    if (!validateVPA(formData.receiverVPA)) {
      newErrors.receiverVPA = 'Receiver VPA must contain @ symbol (e.g., merchant@paytm)';
    }
    
    if (!validateAmount(formData.amount)) {
      newErrors.amount = 'Amount must be a positive number';
    }

    if (!validateVpaAge(formData.receiverVpaAgeDays)) {
      newErrors.receiverVpaAgeDays = 'Enter a whole number of days between 0 and 1000';
    }
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (validateForm() && !isLoading) {
      const age = formData.receiverVpaAgeDays.trim();
      await onSimulate({
        senderVPA: formData.senderVPA,
        receiverVPA: formData.receiverVPA,
        amount: parseFloat(formData.amount),
        ...(age === '' ? {} : { receiverVpaAgeDays: parseInt(age, 10) })
      });
    }
  };

  const handleInputChange = (field: keyof typeof formData, value: string) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    // Clear error when user starts typing
    if (errors[field]) {
      setErrors(prev => ({ ...prev, [field]: undefined }));
    }
  };

  const isFormValid = formData.senderVPA && formData.receiverVPA && formData.amount &&
                     validateVPA(formData.senderVPA) && validateVPA(formData.receiverVPA) && 
                     validateAmount(formData.amount) && validateVpaAge(formData.receiverVpaAgeDays);

  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <h2 className="text-xl font-semibold text-cyan-400 mb-6">Transaction Simulator</h2>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2" htmlFor="senderVPA">
            Sender VPA
          </label>
          <input
            id="senderVPA"
            type="text"
            value={formData.senderVPA}
            onChange={(e) => handleInputChange('senderVPA', e.target.value)}
            placeholder="user@ybl"
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500"
            disabled={isLoading}
            aria-label="Sender VPA"
            aria-describedby={errors.senderVPA ? "senderVPA-error" : undefined}
          />
          {errors.senderVPA && (
            <span id="senderVPA-error" className="text-red-400 text-sm mt-1 block" role="alert">
              {errors.senderVPA}
            </span>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2" htmlFor="receiverVPA">
            Receiver VPA
          </label>
          <input
            id="receiverVPA"
            type="text"
            value={formData.receiverVPA}
            onChange={(e) => handleInputChange('receiverVPA', e.target.value)}
            placeholder="merchant@paytm"
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500"
            disabled={isLoading}
            aria-label="Receiver VPA"
            aria-describedby={errors.receiverVPA ? "receiverVPA-error" : undefined}
          />
          {errors.receiverVPA && (
            <span id="receiverVPA-error" className="text-red-400 text-sm mt-1 block" role="alert">
              {errors.receiverVPA}
            </span>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2" htmlFor="amount">
            Amount (INR)
          </label>
          <input
            id="amount"
            type="number"
            value={formData.amount}
            onChange={(e) => handleInputChange('amount', e.target.value)}
            placeholder="500"
            min="0"
            step="0.01"
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500"
            disabled={isLoading}
            aria-label="Amount in INR"
            aria-describedby={errors.amount ? "amount-error" : undefined}
          />
          {errors.amount && (
            <span id="amount-error" className="text-red-400 text-sm mt-1 block" role="alert">
              {errors.amount}
            </span>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2" htmlFor="receiverVpaAgeDays">
            Receiver VPA Age (days)
            <span className="text-gray-500 font-normal"> — optional</span>
          </label>
          <input
            id="receiverVpaAgeDays"
            type="number"
            value={formData.receiverVpaAgeDays}
            onChange={(e) => handleInputChange('receiverVpaAgeDays', e.target.value)}
            placeholder="0 for a brand-new account"
            min="0"
            max="1000"
            step="1"
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500"
            disabled={isLoading}
            aria-label="Receiver VPA age in days"
            aria-describedby={errors.receiverVpaAgeDays ? "receiverVpaAgeDays-error" : "receiverVpaAgeDays-help"}
          />
          {errors.receiverVpaAgeDays ? (
            <span id="receiverVpaAgeDays-error" className="text-red-400 text-sm mt-1 block" role="alert">
              {errors.receiverVpaAgeDays}
            </span>
          ) : (
            <span id="receiverVpaAgeDays-help" className="text-gray-500 text-xs mt-1 block">
              The model's strongest signal — mule accounts are hours old. Left blank, the
              engine assumes an established account and will approve almost anything.
            </span>
          )}
        </div>

        <button
          type="submit"
          disabled={!isFormValid || isLoading}
          className="w-full bg-cyan-600 hover:bg-cyan-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium py-2 px-4 rounded-md transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:ring-offset-2 focus:ring-offset-gray-800"
          title={!isFormValid ? "Please fill all fields correctly" : undefined}
        >
          {isLoading ? (
            <span className="flex items-center justify-center">
              <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Simulating...
            </span>
          ) : (
            'Simulate Transaction'
          )}
        </button>
      </form>
    </div>
  );
}