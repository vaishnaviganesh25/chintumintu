import { motion } from 'framer-motion';

interface LatencyMetricProps {
  executionTimeMs: number;
}

export function LatencyMetric({ executionTimeMs }: LatencyMetricProps) {
  const isGood = executionTimeMs < 100;
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3, duration: 0.5 }}
      className={`inline-flex items-center px-3 py-1 rounded-md text-sm font-medium ${
        isGood 
          ? 'bg-green-900/30 text-green-400' 
          : 'bg-yellow-900/30 text-yellow-400'
      }`}
    >
      <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      Inference Time: {executionTimeMs}ms
    </motion.div>
  );
}