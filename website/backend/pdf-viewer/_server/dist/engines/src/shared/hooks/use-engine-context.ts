import { useContext } from '@framework';
import { PdfEngineContext, PdfEngineContextState } from '../context';

/**
 * Hook to access the PDF engine from context.
 * @returns The PDF engine context state
 * @throws Error if used outside of PdfEngineProvider
 */
export function useEngineContext(): PdfEngineContextState {
  const contextValue = useContext(PdfEngineContext);

  if (contextValue === undefined) {
    throw new Error('useEngineContext must be used within a PdfEngineProvider');
  }

  return contextValue;
}

/**
 * Hook to access the PDF engine, with a more convenient API.
 * @returns The PDF engine or null if loading/error
 */
export function useEngine() {
  const { engine, error } = useEngineContext();

  if (error) {
    throw error;
  }

  return engine;
}
