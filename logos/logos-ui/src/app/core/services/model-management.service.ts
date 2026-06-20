import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Model, AddModelPayload, UpdateModelPayload } from '../../shared/models/model.model';

@Injectable({ providedIn: 'root' })
export class ModelManagementService {
  private http = inject(HttpClient);

  getModels(): Observable<Model[]> {
    return this.http.post<Model[]>('/api/logosdb/get_models', {});
  }

  addModel(payload: AddModelPayload): Observable<Model> {
    return this.http.post<Model>('/api/logosdb/add_model', payload);
  }

  updateModel(payload: UpdateModelPayload): Observable<Model> {
    return this.http.post<Model>('/api/logosdb/update_model_info', payload);
  }

  deleteModel(id: number): Observable<void> {
    return this.http.post<void>('/api/logosdb/delete_model', { id });
  }
}
