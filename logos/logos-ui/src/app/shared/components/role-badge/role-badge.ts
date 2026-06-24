import {
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnDestroy,
  Output,
  TemplateRef,
  ViewChild,
  ViewContainerRef,
  inject,
  signal,
  ChangeDetectionStrategy,
} from '@angular/core';
import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { UserRole } from '../../../core/auth/models/user.model';
import { ALL_ROLES, ROLE_COLORS, ROLE_DESCRIPTIONS, ROLE_LABELS } from '../../constants/roles';

@Component({
  selector: 'app-role-badge',
  standalone: true,
  templateUrl: './role-badge.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './role-badge.scss',
})
export class RoleBadgeComponent implements OnDestroy {
  @Input() role!: UserRole;
  @Input() clickable = false;
  @Input() allRoles: UserRole[] = ALL_ROLES;
  @Output() roleChange = new EventEmitter<UserRole>();

  @ViewChild('dropdownTpl') dropdownTpl!: TemplateRef<unknown>;

  private overlay = inject(Overlay);
  private vcr = inject(ViewContainerRef);
  private el = inject(ElementRef);

  private overlayRef: OverlayRef | null = null;
  open = signal(false);

  get label(): string {
    return this.role ? (ROLE_LABELS[this.role] ?? this.role) : '-';
  }
  get color(): string {
    return this.role ? ROLE_COLORS[this.role] : 'inherit';
  }

  getLabel(r: UserRole): string {
    return ROLE_LABELS[r];
  }
  getColor(r: UserRole): string {
    return ROLE_COLORS[r];
  }
  getDescription(r: UserRole): string {
    return ROLE_DESCRIPTIONS[r];
  }

  toggleDropdown(): void {
    if (!this.clickable) return;
    if (this.open()) {
      this.close();
      return;
    }

    const positionStrategy = this.overlay
      .position()
      .flexibleConnectedTo(this.el)
      .withPositions([
        { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 6 },
        { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -6 },
      ]);

    this.overlayRef = this.overlay.create({
      positionStrategy,
      scrollStrategy: this.overlay.scrollStrategies.close(),
      hasBackdrop: true,
      backdropClass: 'cdk-overlay-transparent-backdrop',
    });

    this.overlayRef.backdropClick().subscribe(() => this.close());
    this.overlayRef.keydownEvents().subscribe((e) => {
      if (e.key === 'Escape') this.close();
    });
    this.overlayRef.attach(new TemplatePortal(this.dropdownTpl, this.vcr));
    this.open.set(true);
  }

  selectRole(r: UserRole): void {
    if (r !== this.role) this.roleChange.emit(r);
    this.close();
  }

  private close(): void {
    this.overlayRef?.dispose();
    this.overlayRef = null;
    this.open.set(false);
  }

  ngOnDestroy(): void {
    this.close();
  }
}
