import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="min-h-screen flex items-center justify-center bg-slate-100 p-6">
            <div className="bg-white rounded-2xl border border-red-200 p-8 max-w-md text-center space-y-3">
              <div className="text-2xl">⚠</div>
              <h1 className="text-lg font-semibold text-slate-900">Something went wrong</h1>
              <p className="text-sm text-slate-500">
                {this.state.error?.message ?? "An unexpected error occurred."}
              </p>
              <button
                onClick={() => { this.setState({ hasError: false, error: null }); location.reload(); }}
                className="bg-slate-900 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-700"
              >
                Reload page
              </button>
            </div>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
