import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { PriceProviderCard } from './model-prices';

/**
 * Contents of the Prices tab: one card per cloud provider with its rate
 * table. A separate component (and therefore a separate style budget)
 * because the parent's stylesheet already sits at the repo's 16 kB
 * component-style limit.
 */
@Component({
  selector: 'app-model-prices-tab',
  standalone: true,
  imports: [ErrorMessageComponent],
  templateUrl: './model-prices-tab.html',
  styleUrl: './model-prices-tab.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModelPricesTab {
  @Input() loading = false;
  @Input() hasError = false;
  @Input() cards: readonly PriceProviderCard[] = [];
}
