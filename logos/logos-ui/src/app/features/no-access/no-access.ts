import { Component, ChangeDetectionStrategy } from '@angular/core';

@Component({
  selector: 'app-no-access',
  standalone: true,
  templateUrl: './no-access.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './no-access.scss',
})
export class NoAccess {}
