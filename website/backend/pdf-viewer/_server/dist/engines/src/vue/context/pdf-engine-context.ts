import { InjectionKey, Ref } from 'vue';
import type { PdfEngine } from '@embedpdf/models';

export interface PdfEngineContextState {
  engine: Ref<PdfEngine | null>;
  isLoading: Ref<boolean>;
  error: Ref<Error | null>;
}

export const pdfEngineKey: InjectionKey<PdfEngineContextState> = Symbol('pdfEngineKey');
