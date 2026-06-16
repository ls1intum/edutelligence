import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

// Placeholder — will redirect to Keycloak when auth is integrated.
@Component({
  selector: 'app-login',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './login.html',
})
export class Login {}
