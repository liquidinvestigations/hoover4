import { createContext } from '@framework';
import type { PdfEngine } from '@embedpdf/models';

export interface PdfEngineContextState {
  engine: PdfEngine | null;
  isLoading: boolean;
  error: Error | null;
}

export const PdfEngineContext = createContext<PdfEngineContextState | undefined>(undefined);
