import {
  ApplicationConfig,
  provideBrowserGlobalErrorListeners,
  provideZonelessChangeDetection,
  provideAppInitializer,
} from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import { routes } from './app.routes';
import { authInterceptor } from './core/auth/interceptors/auth.interceptor';
import { KEYCLOAK, getKeycloak, initKeycloak } from './core/auth/keycloak';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(withFetch(), withInterceptors([authInterceptor])),
    provideAppInitializer(async () => {
      await initKeycloak();
    }),
    { provide: KEYCLOAK, useFactory: getKeycloak },
  ],
};
