import { inject } from 'vue';
import { pdfEngineKey, PdfEngineContextState } from '../context/pdf-engine-context';

/**
 * Composable to access the PDF engine from context.
 * @returns The PDF engine context state
 * @throws Error if used outside of PdfEngineProvider
 */
export function useEngineContext(): PdfEngineContextState {
  const contextValue = inject(pdfEngineKey);

  if (!contextValue) {
    throw new Error('useEngineContext must be used within a PdfEngineProvider');
  }

  return contextValue;
}

/**
 * Composable to access the PDF engine, with a more convenient API.
 * @returns The PDF engine or null if loading/error
 */
export function useEngine() {
  const { engine, error } = useEngineContext();

  if (error.value) {
    throw error.value;
  }

  return engine;
}
