import { motion } from 'framer-motion';

interface StatusBadgeProps {
  status: 'BLOCKED' | 'APPROVED';
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const isBlocked = status === 'BLOCKED';
  
  return (
    <motion.div
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ duration: 0.5 }}
      className={`inline-flex items-center px-4 py-2 rounded-full text-sm font-bold ${
        isBlocked 
          ? 'bg-red-900/30 text-red-400 border border-red-500' 
          : 'bg-green-900/30 text-green-400 border border-green-500'
      }`}
      role="alert"
      aria-live="polite"
    >
      <span className={`w-2 h-2 rounded-full mr-2 ${
        isBlocked ? 'bg-red-400' : 'bg-green-400'
      }`}></span>
      {isBlocked ? 'TRANSACTION BLOCKED' : 'APPROVED'}
    </motion.div>
  );
}