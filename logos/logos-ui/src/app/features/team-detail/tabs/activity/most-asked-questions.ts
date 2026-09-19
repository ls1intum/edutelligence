import { Component, ChangeDetectionStrategy, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

import { TeamMostAskedQuestion } from './activity-tab.models';

@Component({
  selector: 'app-stats-most-asked-questions',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './most-asked-questions.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './most-asked-questions.scss',
})
export class MostAskedQuestions {
  @Input() questions: TeamMostAskedQuestion[] = [];

  trackByQuestion(_index: number, item: TeamMostAskedQuestion): string {
    return item.question;
  }
}
