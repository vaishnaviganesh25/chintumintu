export function LoadingSpinner() {
  return (
    <div className="flex justify-center items-center h-64" data-testid="loading-spinner">
      <div className="relative">
        <div className="w-16 h-16 border-4 border-gray-600 border-t-cyan-500 rounded-full animate-spin"></div>
        <div className="absolute inset-0 w-16 h-16 border-4 border-transparent border-b-cyan-400 rounded-full animate-spin animate-reverse" style={{ animationDelay: '0.15s' }}></div>
      </div>
    </div>
  );
}