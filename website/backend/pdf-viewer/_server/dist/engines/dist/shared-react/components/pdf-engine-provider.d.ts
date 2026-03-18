import { ReactNode } from '../../react/adapter.ts';
import { PdfEngine } from '@embedpdf/models';
export interface PdfEngineProviderProps {
    children: ReactNode;
    engine: PdfEngine | null;
    isLoading: boolean;
    error: Error | null;
}
/**
 * Provider component that makes a PDF engine instance available
 * to all child components via context.
 *
 * This provider is completely engine-agnostic - it accepts any engine
 * and its loading state from the parent component.
 */
export declare function PdfEngineProvider({ children, engine, isLoading, error }: PdfEngineProviderProps): import("react/jsx-runtime").JSX.Element;
